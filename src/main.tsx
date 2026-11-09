/// <reference types="vite/client" />
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { convertBlobToWav } from './audioUtils';
import './styles.css';

type Profile = Record<string, any>;

type EligibilityRule = {
  field: string;
  operator: string;
  value: any;
  label: string;
};

type Scheme = {
  id: string;
  name: string;
  short_description: string;
  ministry?: string;
  department?: string;
  level?: string;
  target_group?: string;
  categories?: string[];
  state_scope?: string;
  benefit_summary: string;
  benefit_amount: string;
  eligibility_rules?: EligibilityRule[];
  source_verified_at: string;
  application_status: string;
  official_source_url: string;
  required_documents: string[];
  application_steps: string[];
  disclaimer?: string;
};

type EvaluationResult = {
  status: 'likely_match' | 'possible_match' | 'not_match' | string;
  matched: string[];
  unmatched: string[];
  missing: string[];
  documents?: string[];
};

type Match = {
  scheme: Scheme;
  result: EvaluationResult;
};

type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  spokenText?: string;
  ttsLanguage?: string;
  timestamp: string;
  sourceMode?: 'gnani-stt' | 'browser-stt' | 'text';
  extractedFields?: Record<string, any>;
  highlightedSchemes?: Match[];
  followUpQuestions?: string[];
  deterministicBadge?: boolean;
};

type VoiceStatus = {
  gnani_configured: boolean;
  openai_configured: boolean;
  provider: string;
  base_url: string;
  stt_model: string;
  tts_model: string;
  default_voice: string;
  supported_voices: string[];
};

type LangMode = 'HINGLISH' | 'HI' | 'EN';

const API = '/api';

const fallbackMatches: Match[] = [
  {
    scheme: {
      id: 'pragati',
      name: 'AICTE Pragati Scholarship - Technical Degree',
      short_description: 'Support for eligible female technical-degree students.',
      ministry: 'Ministry of Education',
      state_scope: 'India',
      benefit_summary: 'Scholarship support in technical education.',
      benefit_amount: '₹50,000/year (verify current handbook)',
      source_verified_at: '2026-08-29',
      application_status: 'Verification required',
      official_source_url: 'https://aicte-india.org/schemes/students-development-schemes',
      required_documents: ['Income certificate', 'Admission details', 'Marksheet'],
      application_steps: ['Check the current AICTE notice', 'Confirm institution approval', 'Use the official portal'],
    },
    result: {
      status: 'likely_match',
      matched: ['Applicant is female', 'Studying a technical degree', 'Family income is within ₹8 lakh'],
      unmatched: [],
      missing: ['Institution is AICTE approved'],
    },
  },
  {
    scheme: {
      id: 'pm-usp',
      name: 'PM-USP Central Sector Scheme of Scholarship',
      short_description: 'Merit-cum-means support for eligible regular college students.',
      ministry: 'Ministry of Education',
      state_scope: 'India',
      benefit_summary: 'Support toward study expenses.',
      benefit_amount: '₹12,000/year at graduation level (verify current notice)',
      source_verified_at: '2026-08-29',
      application_status: 'Verification required for 2026-27 window',
      official_source_url: 'https://www.education.gov.in/sites/upload_files/mhrd/files/upload_document/FAQs_PM_USP2526.pdf',
      required_documents: ['Class XII marksheet', 'Income certificate', 'Institution details'],
      application_steps: ['Confirm the current NSP window', 'Prepare your checklist', 'Apply on the official portal'],
    },
    result: {
      status: 'possible_match',
      matched: ['Pursuing a regular higher-education course', 'Family income is within ₹4.5 lakh'],
      unmatched: [],
      missing: ['Class XII result is at or above the 80th percentile', 'Not receiving another scholarship'],
    },
  },
  {
    scheme: {
      id: 'saksham',
      name: 'AICTE Saksham Scholarship - Technical Degree',
      short_description: 'Technical education support for students with disabilities.',
      ministry: 'Ministry of Education',
      state_scope: 'India',
      benefit_summary: 'Scholarship support in technical education.',
      benefit_amount: '₹50,000/year (verify current handbook)',
      source_verified_at: '2026-08-29',
      application_status: 'Verification required',
      official_source_url: 'https://aicte-india.org/schemes/students-development-schemes',
      required_documents: ['Disability certificate', 'Income certificate', 'Institution details'],
      application_steps: ['Review the current AICTE notice', 'Check certificate requirements', 'Use the official portal'],
    },
    result: {
      status: 'not_match',
      matched: ['Studying a technical degree'],
      unmatched: ['Reported disability status'],
      missing: [],
    },
  },
];

const demos: Record<string, Profile> = {
  student: {
    name: 'Aarav Sharma',
    age: 20,
    gender: 'Male',
    state: 'Rajasthan',
    education_level: 'B.Tech',
    year_of_study: '2nd year',
    annual_income: 240000,
    class12_percentile: 84,
    other_scholarship: false,
    institution_type: 'AICTE approved',
    category: 'General',
    disability_status: false,
  },
  woman: {
    name: 'Meera Verma',
    age: 19,
    gender: 'Female',
    state: 'Uttar Pradesh',
    education_level: 'B.Tech',
    year_of_study: '1st year',
    annual_income: 350000,
    class12_percentile: 86,
    other_scholarship: false,
    institution_type: 'AICTE approved',
    category: 'OBC',
    disability_status: false,
  },
  mother: {
    name: 'Nisha Kumari',
    age: 25,
    gender: 'Female',
    state: 'Bihar',
    annual_income: 300000,
    pregnancy_status: true,
    benefit_category: 'Income based',
  },
};

const questions = [
  ['age', 'How old are you?', 'number'],
  ['gender', 'What is your gender?', 'select:Female|Male|Prefer not to say'],
  ['education_level', 'What are you studying?', 'select:B.Tech|Diploma|BA|BSc|Other'],
  ['year_of_study', 'Which year are you in?', 'select:1st year|2nd year|3rd year|4th year'],
  ['annual_income', 'Approximate annual family income (₹)', 'number'],
  ['class12_percentile', 'Class XII percentile (if known)', 'number'],
  ['institution_type', 'Your institution type', 'select:AICTE approved|Government college|Private college|Not sure'],
  ['other_scholarship', 'Do you receive another scholarship?', 'select:No|Yes'],
];

const SAMPLE_VOICE_PROMPTS = [
  {
    label: ' राजस्थान · ₹1.5L आय',
    query: 'Meri family ki income 1.5 lakh hai. Main Rajasthan se hoon. Mujhe kaunsi government schemes mil sakti hain?',
  },
  {
    label: '🎓 Student Scholarships',
    query: 'Mujhe students ke liye scholarships batao.',
  },
  {
    label: '🏠 PM Awas Eligibility',
    query: 'Kya main PM Awas Yojana ke liye eligible hoon?',
  },
  {
    label: '📄 No Income Certificate',
    query: 'Mere paas income certificate nahi hai.',
  },
  {
    label: '👩 Rajasthan Women Schemes',
    query: 'Rajasthan mein women ke liye schemes batao.',
  },
  {
    label: '✓ Verified Schemes Only',
    query: 'Mujhe sirf government verified schemes chahiye.',
  },
];

function formatFieldLabel(key: string): string {
  const map: Record<string, string> = {
    annual_income: 'Annual Income',
    state: 'State',
    gender: 'Gender',
    age: 'Age',
    education_level: 'Education',
    class12_percentile: '12th Percentile',
    institution_type: 'Institution',
    category: 'Category',
    pregnancy_status: 'Maternity/Pregnant',
    disability_status: 'Disability Status',
    has_pucca_house: 'Owns Pucca House',
    child_age: 'Child Age',
    child_gender: 'Child Gender',
    other_scholarship: 'Other Scholarship',
  };
  return map[key] || key.replace(/_/g, ' ');
}

function formatFieldValue(key: string, val: any): string {
  if (key === 'annual_income' && typeof val === 'number') {
    return `₹${val.toLocaleString('en-IN')}`;
  }
  if (typeof val === 'boolean') {
    return val ? 'Yes' : 'No';
  }
  return String(val);
}

function App() {
  const [page, setPage] = useState<string>('home');
  const [lang, setLang] = useState<LangMode>('HINGLISH');
  const [profile, setProfile] = useState<Profile>({});
  const [i, setI] = useState(0);
  const [goal, setGoal] = useState('');
  const [matches, setMatches] = useState<Match[]>([]);
  const [selected, setSelected] = useState<Match | null>(null);
  const [docs, setDocs] = useState<Record<string, boolean>>({});
  const [appId, setAppId] = useState('');

  // Dashboard filters
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'likely_match' | 'possible_match' | 'not_match'>('ALL');
  const [aiExplanation, setAiExplanation] = useState<string>('');
  const [explaining, setExplaining] = useState<boolean>(false);

  // Voice & Conversational Assistant State
  const [voiceStatus, setVoiceStatus] = useState<VoiceStatus | null>(null);
  const [selectedVoice, setSelectedVoice] = useState<string>('Nalini');
  const [autoSpeak, setAutoSpeak] = useState<boolean>(true);
  const [chatInput, setChatInput] = useState<string>('');
  const [chatLoading, setChatLoading] = useState<boolean>(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'welcome-1',
      role: 'assistant',
      text: 'Namaste! Main **Mera Adhikaar Voice Assistant** hoon (powered by **Gnani AI**). Aap mujhse Hindi, Hinglish, ya English mein bolkar ya likhkar apne liye sahi sarkari yojanaएं (welfare schemes) khoj sakte hain.\n\nUdaharan ke liye boliye: *"Meri family ki income 1.5 lakh hai, main Rajasthan se hoon, mujhe kaunsi schemes mil sakti hain?"*',
      spokenText:
        'नमस्ते! मैं मेरा अधिकार वॉइस असिस्टेंट हूँ। आप मुझसे हिंदी, हिंग्लिश या इंग्लिश में बोलकर सरकारी योजनाएं खोज सकते हैं।',
      ttsLanguage: 'hi-IN',
      timestamp: 'Just now',
      deterministicBadge: true,
      followUpQuestions: [
        'Meri family ki income 1.5 lakh hai. Main Rajasthan se hoon. Mujhe kaunsi government schemes mil sakti hain?',
        'Mujhe students ke liye scholarships batao.',
        'Kya main PM Awas Yojana ke liye eligible hoon?',
      ],
    },
  ]);

  // Recording / STT / TTS states
  const [isRecording, setIsRecording] = useState<boolean>(false);
  const [recordingSeconds, setRecordingSeconds] = useState<number>(0);
  const [isTranscribing, setIsTranscribing] = useState<boolean>(false);
  const [isSpeaking, setIsSpeaking] = useState<boolean>(false);
  const [speakingProvider, setSpeakingProvider] = useState<'gnani-timbre' | 'browser-tts' | null>(null);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  const [permissionDenied, setPermissionDenied] = useState<boolean>(false);
  const [lastRecordedBlob, setLastRecordedBlob] = useState<Blob | null>(null);
  const [waveBars, setWaveBars] = useState<number[]>(new Array(20).fill(14));

  // Refs for audio & recording
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const animFrameRef = useRef<number | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const timerRef = useRef<number | null>(null);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const chatEndRef = useRef<HTMLDivElement | null>(null);

  const t = (en: string, hi: string, hinglish?: string) => {
    if (lang === 'EN') return en;
    if (lang === 'HI') return hi;
    return hinglish || en;
  };

  // Initial fetch of schemes, eligibility, and Gnani AI voice status
  useEffect(() => {
    fetch(`${API}/voice/status`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) {
          setVoiceStatus(data);
          if (data.default_voice) setSelectedVoice(data.default_voice);
        }
      })
      .catch(() => {});

    refreshEligibility({});
  }, []);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, chatLoading]);

  const refreshEligibility = async (nextProfile: Profile) => {
    try {
      const r = await fetch(`${API}/eligibility`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile: nextProfile }),
      });
      if (!r.ok) throw new Error('Failed eligibility');
      const data = await r.json();
      setMatches(data);
      return data as Match[];
    } catch {
      setMatches(fallbackMatches);
      return fallbackMatches;
    }
  };

  const stopSpeaking = () => {
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current.currentTime = 0;
      currentAudioRef.current = null;
    }
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    setIsSpeaking(false);
    setSpeakingProvider(null);
  };

  const speakWithBrowserFallback = (text: string, langCode: string) => {
    if (!('speechSynthesis' in window)) {
      setVoiceError('Speech synthesis is not available in this browser.');
      return;
    }
    stopSpeaking();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = langCode === 'en-IN' ? 'en-IN' : 'hi-IN';
    utterance.rate = 1.0;
    utterance.onstart = () => {
      setIsSpeaking(true);
      setSpeakingProvider('browser-tts');
    };
    utterance.onend = () => {
      setIsSpeaking(false);
      setSpeakingProvider(null);
    };
    utterance.onerror = () => {
      setIsSpeaking(false);
      setSpeakingProvider(null);
    };
    window.speechSynthesis.speak(utterance);
  };

  const speakResponse = async (textToSpeak: string, ttsLang = 'hi-IN') => {
    if (!textToSpeak) return;
    stopSpeaking();
    setVoiceError(null);

    try {
      setIsSpeaking(true);
      setSpeakingProvider('gnani-timbre');
      const res = await fetch(`${API}/voice/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          text: textToSpeak,
          language: ttsLang,
          voice: selectedVoice,
          model: voiceStatus?.tts_model || 'timbre-v2.5',
          speed: 1.0,
        }),
      });

      if (!res.ok) {
        let errMsg = `Gnani TTS returned ${res.status}`;
        try {
          const errJson = await res.json();
          errMsg = errJson.message || errMsg;
        } catch {}
        setIsSpeaking(false);
        setSpeakingProvider(null);
        // Use browser speech synthesis as explicit accessibility fallback while showing transparent notice
        speakWithBrowserFallback(textToSpeak, ttsLang);
        if (res.status !== 503) {
          setVoiceError(`${errMsg} (Using Browser Voice Fallback)`);
        }
        return;
      }

      const audioBlob = await res.blob();
      const audioUrl = URL.createObjectURL(audioBlob);
      const audio = new Audio(audioUrl);
      currentAudioRef.current = audio;

      audio.onended = () => {
        setIsSpeaking(false);
        setSpeakingProvider(null);
        URL.revokeObjectURL(audioUrl);
      };
      audio.onerror = () => {
        setIsSpeaking(false);
        setSpeakingProvider(null);
        URL.revokeObjectURL(audioUrl);
        speakWithBrowserFallback(textToSpeak, ttsLang);
      };
      await audio.play();
    } catch {
      setIsSpeaking(false);
      setSpeakingProvider(null);
      speakWithBrowserFallback(textToSpeak, ttsLang);
    }
  };

  // Cleanup microphone & animation resources
  const cleanupRecordingResources = () => {
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
    if (timerRef.current) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach((track) => track.stop());
      mediaStreamRef.current = null;
    }
    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
    setWaveBars(new Array(20).fill(14));
  };

  const startRecording = async () => {
    stopSpeaking();
    setVoiceError(null);
    setPermissionDenied(false);

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setVoiceError('Microphone recording is not supported in this browser. Please use text input.');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaStreamRef.current = stream;
      audioChunksRef.current = [];

      // Set up real-time AnalyserNode waveform visualization
      const AudioCtx =
        window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const audioCtx = new AudioCtx();
      audioCtxRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 64;
      source.connect(analyser);
      const dataArray = new Uint8Array(analyser.frequencyBinCount);

      const updateWaveform = () => {
        analyser.getByteFrequencyData(dataArray);
        const bars: number[] = [];
        for (let idx = 0; idx < 20; idx++) {
          const val = dataArray[idx % dataArray.length] || 0;
          bars.push(Math.max(12, Math.min(96, Math.round((val / 255) * 95))));
        }
        setWaveBars(bars);
        animFrameRef.current = requestAnimationFrame(updateWaveform);
      };
      animFrameRef.current = requestAnimationFrame(updateWaveform);

      const recorder = new MediaRecorder(stream);
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          audioChunksRef.current.push(event.data);
        }
      };

      recorder.onstop = async () => {
        const rawBlob = new Blob(audioChunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        cleanupRecordingResources();
        setIsRecording(false);
        if (rawBlob.size > 100) {
          const wavBlob = await convertBlobToWav(rawBlob);
          setLastRecordedBlob(wavBlob);
          await processAudioWithGnaniSTT(wavBlob);
        } else {
          setVoiceError('No audio was captured. Please hold the microphone button and speak clearly.');
        }
      };

      recorder.start();
      setIsRecording(true);
      setRecordingSeconds(0);
      timerRef.current = window.setInterval(() => {
        setRecordingSeconds((prev) => {
          if (prev >= 29) {
            stopRecording();
            return 30;
          }
          return prev + 1;
        });
      }, 1000);
    } catch (err: any) {
      cleanupRecordingResources();
      setIsRecording(false);
      if (err && (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError')) {
        setPermissionDenied(true);
        setVoiceError(
          'Microphone permission was denied. Please allow microphone access in your browser address bar or use the text chat below.'
        );
      } else {
        setVoiceError('Could not access microphone. Please check your audio device or use text input below.');
      }
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop();
    } else {
      cleanupRecordingResources();
      setIsRecording(false);
    }
  };

  const startBrowserWebSpeechFallback = () => {
    const SpeechRec =
      (window as unknown as { SpeechRecognition?: any; webkitSpeechRecognition?: any }).SpeechRecognition ||
      (window as unknown as { webkitSpeechRecognition?: any }).webkitSpeechRecognition;
    if (!SpeechRec) {
      setVoiceError('Browser Web Speech API is not supported in this browser. Please type your question below.');
      return;
    }
    setVoiceError(null);
    stopSpeaking();
    const rec = new SpeechRec();
    rec.lang = lang === 'EN' ? 'en-IN' : 'hi-IN';
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    setIsTranscribing(true);
    rec.onresult = (event: any) => {
      setIsTranscribing(false);
      const transcript = event.results?.[0]?.[0]?.transcript;
      if (transcript) {
        sendChatMessage(transcript, 'browser-stt');
      }
    };
    rec.onerror = () => {
      setIsTranscribing(false);
      setVoiceError('Browser speech recognition could not capture audio. Please type your message or retry.');
    };
    rec.onend = () => {
      setIsTranscribing(false);
    };
    rec.start();
  };

  const processAudioWithGnaniSTT = async (wavBlob: Blob) => {
    setIsTranscribing(true);
    setVoiceError(null);
    try {
      const formData = new FormData();
      formData.append('audio_file', wavBlob, 'recording.wav');
      const langCode = lang === 'EN' ? 'en-IN' : lang === 'HI' ? 'hi-IN' : 'indic-auto';
      formData.append('language_code', langCode);
      formData.append('model', voiceStatus?.stt_model || 'prisma-v3.0');
      formData.append('format', 'transcribe');

      const res = await fetch(`${API}/voice/stt`, {
        method: 'POST',
        body: formData,
      });

      const data = await res.json();
      setIsTranscribing(false);

      if (!res.ok || !data.success) {
        setVoiceError(
          data.message ||
            'Gnani AI STT could not process this audio. Set GNANI_API_KEY in .env or use Browser Voice / Text below.'
        );
        return;
      }

      if (data.transcript) {
        await sendChatMessage(data.transcript, 'gnani-stt');
      } else {
        setVoiceError('No speech was detected in the recording. Please try speaking again.');
      }
    } catch {
      setIsTranscribing(false);
      setVoiceError('Network error while contacting /api/voice/stt. Please retry or use text input.');
    }
  };

  const sendChatMessage = async (textInput: string, sourceMode: 'gnani-stt' | 'browser-stt' | 'text' = 'text') => {
    const trimmed = textInput.trim();
    if (!trimmed) return;

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      text: trimmed,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      sourceMode,
    };

    setMessages((prev) => [...prev, userMsg]);
    setChatInput('');
    setChatLoading(true);
    setVoiceError(null);

    try {
      const res = await fetch(`${API}/ai/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: trimmed,
          profile,
          language: lang,
          history: messages.slice(-6).map((m) => ({ role: m.role, content: m.text })),
        }),
      });

      if (!res.ok) throw new Error('Chat request failed');
      const data = await res.json();

      if (data.updated_profile) {
        setProfile(data.updated_profile);
      }
      if (data.matches) {
        setMatches(data.matches);
      }

      const assistantMsg: ChatMessage = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        text: data.reply,
        spokenText: data.spoken_reply,
        ttsLanguage: data.tts_language || 'hi-IN',
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        extractedFields: data.extracted_fields,
        highlightedSchemes: data.highlighted_schemes,
        followUpQuestions: data.follow_up_questions,
        deterministicBadge: true,
      };

      setMessages((prev) => [...prev, assistantMsg]);
      setChatLoading(false);

      if (autoSpeak && data.spoken_reply) {
        await speakResponse(data.spoken_reply, data.tts_language || 'hi-IN');
      }
    } catch {
      setChatLoading(false);
      setVoiceError('Could not process your request right now. Please try again.');
    }
  };

  const loadDemo = async (key: string) => {
    const demoProf = demos[key];
    setProfile(demoProf);
    const demoGoal =
      key === 'mother'
        ? 'Pregnancy support and maternity benefits'
        : 'Mujhe college fees ke liye scholarship chahiye';
    setGoal(demoGoal);
    await refreshEligibility(demoProf);
    setPage('summary');
  };

  const next = () => {
    if (i < questions.length - 1) setI(i + 1);
    else setPage('summary');
  };

  const current = questions[i];

  const match = async () => {
    setPage('loading');
    await refreshEligibility(profile);
    setPage('results');
  };

  const handleExplainScheme = async (m: Match) => {
    setSelected(m);
    setAiExplanation('');
    setPage('detail');
    window.scrollTo(0, 0);
    setExplaining(true);
    try {
      const r = await fetch(`${API}/ai/explain-match`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile, scheme_id: m.scheme.id }),
      });
      if (r.ok) {
        const d = await r.json();
        setAiExplanation(d.summary || '');
      }
    } catch {
    } finally {
      setExplaining(false);
    }
  };

  const submit = async () => {
    try {
      const r = await fetch(`${API}/applications`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ profile, scheme_id: selected?.scheme.id }),
      });
      const x = await r.json();
      setAppId(x.id);
    } catch {
      setAppId('MA-2026-4821');
    }
    setPage('tracker');
  };

  const statusBadge = (s: string) =>
    s === 'likely_match'
      ? ['strong', t('Likely Eligible', 'प्रबल पात्रता', 'Likely Match (पात्र)')]
      : s === 'possible_match'
      ? ['possible', t('Potentially Eligible', 'संभावित पात्रता', 'Possible Match (संभावित)')]
      : ['no', t('Does Not Match', 'मानदंड मेल नहीं', 'Not Matching')];

  const go = (p: string) => {
    stopSpeaking();
    setPage(p);
    window.scrollTo(0, 0);
  };

  // Filtered schemes for Dashboard
  const filteredMatches = useMemo(() => {
    return matches.filter((m) => {
      if (statusFilter !== 'ALL' && m.result.status !== statusFilter) return false;
      if (!searchQuery.trim()) return true;
      const q = searchQuery.toLowerCase();
      return (
        m.scheme.name.toLowerCase().includes(q) ||
        m.scheme.short_description.toLowerCase().includes(q) ||
        m.scheme.benefit_summary.toLowerCase().includes(q) ||
        (m.scheme.state_scope || '').toLowerCase().includes(q) ||
        (m.scheme.target_group || '').toLowerCase().includes(q)
      );
    });
  }, [matches, statusFilter, searchQuery]);

  const counts = useMemo(() => {
    return {
      likely: matches.filter((m) => m.result.status === 'likely_match').length,
      possible: matches.filter((m) => m.result.status === 'possible_match').length,
      notMatch: matches.filter((m) => m.result.status === 'not_match').length,
    };
  }, [matches]);

  const renderMarkdownText = (raw: string) => {
    return raw.split('\n').map((line, idx) => {
      const parts = line.split(/(\*\*.*?\*\*)/g);
      return (
        <p key={idx} className="chat-line">
          {parts.map((part, pIdx) =>
            part.startsWith('**') && part.endsWith('**') ? (
              <strong key={pIdx}>{part.slice(2, -2)}</strong>
            ) : (
              <span key={pIdx}>{part}</span>
            )
          )}
        </p>
      );
    });
  };

  const shell = (content: React.ReactNode) => (
    <>
      <header className="top-header">
        <div className="brand-group">
          <button className="brand" onClick={() => go('home')}>
            MERA <span>ADHIKAAR</span> <em className="voice-pill">VOICE</em>
          </button>
          <span className="tagline-chip">Your Voice. Your Rights. Your Schemes.</span>
        </div>

        <nav className="main-nav" aria-label="Primary Navigation">
          <button className={`nav-link ${page === 'home' ? 'active' : ''}`} onClick={() => go('home')}>
            {t('Home', 'होम', 'Home')}
          </button>
          <button className={`nav-link ${page === 'voice' ? 'active' : ''}`} onClick={() => go('voice')}>
            🎙️ {t('Voice Assistant', 'वॉइस असिस्टेंट', 'Voice Sahayak')}
          </button>
          <button className={`nav-link ${page === 'dashboard' ? 'active' : ''}`} onClick={() => go('dashboard')}>
            📋 {t('Scheme Dashboard', 'योजना डैशबोर्ड', 'Schemes')} ({matches.length})
          </button>
          <button className={`nav-link ${page === 'goal' ? 'active' : ''}`} onClick={() => go('goal')}>
            🧭 {t('Guided Check', 'स्टेप-बाय-स्टेप जांच', 'Guided Check')}
          </button>
        </nav>

        <div className="header-controls">
          <div className="lang-switcher" role="group" aria-label="Language Selector">
            {(['HINGLISH', 'HI', 'EN'] as LangMode[]).map((l) => (
              <button
                key={l}
                className={`lang-btn ${lang === l ? 'active' : ''}`}
                onClick={() => setLang(l)}
              >
                {l === 'HI' ? 'हिंदी' : l === 'HINGLISH' ? 'Hinglish' : 'EN'}
              </button>
            ))}
          </div>
          <button
            className="simple"
            onClick={() => document.body.classList.toggle('simple-view')}
            title="Toggle High-Readability Simple View"
          >
            ◐ {t('Simple view', 'सरल दृश्य', 'Simple View')}
          </button>
        </div>
      </header>
      <main>{content}</main>
    </>
  );

  // -------------------------------------------------------------------------
  // PAGE: VOICE ASSISTANT & CONVERSATIONAL SCHEME DISCOVERY
  // -------------------------------------------------------------------------
  if (page === 'voice') {
    return shell(
      <section className="voice-workspace">
        {/* Left / Top Column: Voice Control Center & Extracted Citizen Profile */}
        <aside className="voice-sidebar">
          <div className="voice-card">
            <div className="voice-card-header">
              <span className="eyebrow">GNANI AI VACHANA ENGINE</span>
              <span
                className={`api-status-badge ${
                  voiceStatus?.gnani_configured ? 'connected' : 'fallback-mode'
                }`}
              >
                {voiceStatus?.gnani_configured
                  ? '● Gnani Prisma v3.0 & Timbre v2.5 Active'
                  : '◉ Gnani API Ready (Set GNANI_API_KEY for Live Cloud)'}
              </span>
            </div>

            <h2>{t('Speak Naturally in Hindi, Hinglish, or English', 'अपनी भाषा में बोलकर योजनाएं खोजें', 'Boliye aur Apni Schemes Jaaniye')}</h2>
            <p className="voice-sub">
              {t(
                'Tell us your state, family income, course, or ask about any scheme.',
                'अपना राज्य, पारिवारिक आय, पढ़ाई या किसी भी सरकारी योजना के बारे में पूछें।',
                'Apनी family income, state, padhai ya kisi bhi yojana ke baare mein poochein.'
              )}
            </p>

            {/* Animated Waveform & Microphone Interaction */}
            <div className={`waveform-stage ${isRecording ? 'recording' : isSpeaking ? 'speaking' : ''}`}>
              <div className="waveform-bars" aria-hidden="true">
                {waveBars.map((h, idx) => (
                  <span
                    key={idx}
                    className="wave-bar"
                    style={{
                      height: isRecording
                        ? `${h}%`
                        : isSpeaking
                        ? `${25 + ((idx * 17) % 55)}%`
                        : '16%',
                    }}
                  />
                ))}
              </div>
              <div className="voice-state-label">
                {isRecording ? (
                  <span className="rec-live">
                    ● {t('Recording microphone...', 'आवाज़ रिकॉर्ड हो रही है...', ' सुन रहे हैं...')} ({recordingSeconds}s / 30s)
                  </span>
                ) : isTranscribing ? (
                  <span className="transcribing-live">
                    ⟳ {t('Processing speech via Gnani Prisma STT...', 'Gnani AI आवाज़ समझ रहा है...', 'Gnani AI speech process kar raha hai...')}
                  </span>
                ) : isSpeaking ? (
                  <span className="speaking-live">
                    🔊 {t('Assistant speaking', 'सहायक बोल रहा है', 'Assistant bol raha hai')} (
                    {speakingProvider === 'gnani-timbre' ? `Gnani Timbre · ${selectedVoice}` : 'Browser Voice'})
                  </span>
                ) : (
                  <span className="idle-label">
                    {t('Tap the microphone to start speaking', 'बोलने के लिए माइक बटन दबाएं', 'Bolne ke liye Mic button dabayein')}
                  </span>
                )}
              </div>
            </div>

            {/* Primary Voice Controls */}
            <div className="mic-actions">
              {!isRecording ? (
                <button
                  type="button"
                  className="mic-btn"
                  onClick={startRecording}
                  disabled={isTranscribing}
                  aria-label="Start Microphone Recording"
                >
                  <span className="mic-icon">🎙️</span>
                  <span>
                    {t(
                      'Start Speaking (Gnani STT)',
                      'माइक से बोलें (Gnani STT)',
                      'Mic se Bolein (Gnani AI)'
                    )}
                  </span>
                </button>
              ) : (
                <button
                  type="button"
                  className="mic-btn stop-rec"
                  onClick={stopRecording}
                  aria-label="Stop Recording and Transcribe"
                >
                  <span className="mic-icon">⏹</span>
                  <span>{t('Done Speaking — Find Schemes', 'रिकॉर्डिंग पूरी करें', 'Bol Liya — Schemes Khojein')}</span>
                </button>
              )}

              {isSpeaking && (
                <button
                  type="button"
                  className="secondary stop-speak-btn"
                  onClick={stopSpeaking}
                >
                  🔇 {t('Stop Speaking', 'आवाज़ रोकें', 'Awaaz Rokein')}
                </button>
              )}
            </div>

            {/* Secondary Controls: Browser STT Fallback + Voice Selector */}
            <div className="voice-toolbar">
              <button
                type="button"
                className="text-fallback-btn"
                onClick={startBrowserWebSpeechFallback}
                disabled={isRecording || isTranscribing}
                title="Use browser built-in speech recognition if Gnani API key is not configured"
              >
                🌐 {t('Browser Mic Fallback', 'ब्राउज़र माइक विकल्प', 'Browser Mic Fallback')}
              </button>

              <label className="voice-select-label">
                <span>TTS Voice:</span>
                <select
                  value={selectedVoice}
                  onChange={(e) => setSelectedVoice(e.target.value)}
                  aria-label="Select Gnani Timbre Voice"
                >
                  {(voiceStatus?.supported_voices || ['Nalini', 'Karan', 'Simran', 'Raju']).map((v) => (
                    <option key={v} value={v}>
                      {v} (Timbre v2.5)
                    </option>
                  ))}
                </select>
              </label>

              <label className="autospeak-toggle">
                <input
                  type="checkbox"
                  checked={autoSpeak}
                  onChange={(e) => setAutoSpeak(e.target.checked)}
                />
                <span>{t('Auto-speak', 'ऑटो-वॉइस', 'Auto Voice')}</span>
              </label>
            </div>

            {/* Error State & Retry Handler */}
            {voiceError && (
              <div className="voice-error-banner" role="alert">
                <p>⚠️ {voiceError}</p>
                <div className="error-actions">
                  {lastRecordedBlob && (
                    <button
                      type="button"
                      className="retry-btn"
                      onClick={() => processAudioWithGnaniSTT(lastRecordedBlob)}
                    >
                      ↻ {t('Retry Gnani STT', 'पुनः प्रयास करें', 'Retry Gnani STT')}
                    </button>
                  )}
                  <button
                    type="button"
                    className="retry-btn"
                    onClick={startBrowserWebSpeechFallback}
                  >
                    🎙️ {t('Try Browser Voice', 'ब्राउज़र वॉइस आज़माएं', 'Use Browser Voice')}
                  </button>
                  {permissionDenied && (
                    <button type="button" className="retry-btn" onClick={startRecording}>
                      🔓 {t('Re-request Mic Permission', 'माइक अनुमति दें', 'Allow Mic')}
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Live Extracted Citizen Profile & Deterministic Summary */}
          <div className="live-profile-panel">
            <div className="panel-head">
              <h3>👤 {t('Detected Citizen Profile', 'आपकी प्रोफ़ाइल जानकारी', 'Aapki Extracted Profile')}</h3>
              {Object.keys(profile).length > 0 && (
                <button
                  type="button"
                  className="clear-btn"
                  onClick={() => {
                    setProfile({});
                    refreshEligibility({});
                  }}
                >
                  {t('Reset', 'रीसेट', 'Reset')}
                </button>
              )}
            </div>

            {Object.keys(profile).length === 0 ? (
              <p className="empty-profile-hint">
                {t(
                  'As you speak or chat, details like your state, family income, age, and course will appear here automatically.',
                  'जब आप बोलेंगे या लिखेंगे, तो आपका राज्य, आय, उम्र और शिक्षा अपने आप यहाँ जुड़ जाएंगे।',
                  'Jaise hi aap bolenge, aapka state, income, age aur education yahan automatically dikhega.'
                )}
              </p>
            ) : (
              <div className="profile-chips">
                {Object.entries(profile)
                  .filter(([k]) => k !== 'name')
                  .map(([k, v]) => (
                    <div key={k} className="profile-chip">
                      <span>{formatFieldLabel(k)}</span>
                      <b>{formatFieldValue(k, v)}</b>
                    </div>
                  ))}
              </div>
            )}

            <div className="live-counts-bar">
              <button
                type="button"
                className="count-box strong"
                onClick={() => {
                  setStatusFilter('likely_match');
                  go('dashboard');
                }}
              >
                <b>{counts.likely}</b>
                <span>{t('Likely Eligible', 'प्रबल पात्र', 'Likely')}</span>
              </button>
              <button
                type="button"
                className="count-box possible"
                onClick={() => {
                  setStatusFilter('possible_match');
                  go('dashboard');
                }}
              >
                <b>{counts.possible}</b>
                <span>{t('Potential', 'संभावित', 'Possible')}</span>
              </button>
              <button
                type="button"
                className="count-box no"
                onClick={() => {
                  setStatusFilter('not_match');
                  go('dashboard');
                }}
              >
                <b>{counts.notMatch}</b>
                <span>{t('Ineligible', 'अपात्र', 'Ineligible')}</span>
              </button>
            </div>
          </div>
        </aside>

        {/* Right / Main Column: Conversational Discovery Thread */}
        <div className="chat-column">
          <div className="sample-prompts-bar">
            <span className="prompt-bar-title">
              {t('Try saying or clicking:', 'बोलें या क्लिक करके पूछें:', 'Bolkar ya click karke poochein:')}
            </span>
            <div className="prompt-chips">
              {SAMPLE_VOICE_PROMPTS.map((item) => (
                <button
                  key={item.label}
                  type="button"
                  className="prompt-chip"
                  onClick={() => sendChatMessage(item.query, 'text')}
                  disabled={chatLoading}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          <div className="chat-messages" role="log" aria-live="polite">
            {messages.map((msg) => (
              <article key={msg.id} className={`chat-bubble ${msg.role}`}>
                <div className="bubble-meta">
                  <span className="sender-name">
                    {msg.role === 'user'
                      ? `🧑 ${t('You', 'आप', 'Aap')}`
                      : '🇮🇳 Mera Adhikaar Voice'}
                  </span>
                  {msg.sourceMode === 'gnani-stt' && (
                    <span className="source-pill gnani">🎙️ Gnani Prisma STT</span>
                  )}
                  {msg.sourceMode === 'browser-stt' && (
                    <span className="source-pill browser">🎙️ Voice Input</span>
                  )}
                  {msg.deterministicBadge && (
                    <span className="source-pill deterministic">
                      ✓ Deterministic Rules Verified
                    </span>
                  )}
                  <time>{msg.timestamp}</time>
                </div>

                <div className="bubble-body">{renderMarkdownText(msg.text)}</div>

                {/* Newly extracted profile attributes badge */}
                {msg.extractedFields && Object.keys(msg.extractedFields).length > 0 && (
                  <div className="extracted-tags">
                    <small>{t('Understood from your voice/message:', 'समझी गई जानकारी:', 'Extracted Details:')}</small>
                    {Object.entries(msg.extractedFields).map(([k, v]) => (
                      <span key={k} className="ext-tag">
                        + {formatFieldLabel(k)}: <b>{formatFieldValue(k, v)}</b>
                      </span>
                    ))}
                  </div>
                )}

                {/* Inline Highlighted Scheme Cards from Deterministic Engine */}
                {msg.highlightedSchemes && msg.highlightedSchemes.length > 0 && (
                  <div className="inline-schemes">
                    {msg.highlightedSchemes.slice(0, 3).map((m) => {
                      const [c, badgeLabel] = statusBadge(m.result.status);
                      return (
                        <div key={m.scheme.id} className="inline-scheme-card">
                          <div className="inline-scheme-top">
                            <span className={`pill ${c}`}>{badgeLabel}</span>
                            <small>Verified: {m.scheme.source_verified_at}</small>
                          </div>
                          <h4>{m.scheme.name}</h4>
                          <p className="inline-benefit">{m.scheme.benefit_amount}</p>
                          {m.result.matched.length > 0 && (
                            <p className="inline-matched">
                              ✓ {m.result.matched.slice(0, 2).join(' · ')}
                            </p>
                          )}
                          {m.result.missing.length > 0 && (
                            <p className="inline-missing">
                              ! {t('To confirm:', 'पुष्टि करें:', 'Need to check:')} {m.result.missing.slice(0, 2).join(' · ')}
                            </p>
                          )}
                          <div className="inline-scheme-actions">
                            <button
                              type="button"
                              className="secondary small-btn"
                              onClick={() => handleExplainScheme(m)}
                            >
                              {t('Full Eligibility & Docs', 'पात्रता और दस्तावेज़', 'Eligibility & Docs')} →
                            </button>
                            <a
                              href={m.scheme.official_source_url}
                              target="_blank"
                              rel="noreferrer"
                              className="official-link"
                            >
                              {t('Official Portal', 'आधिकारिक पोर्टल', 'Official Site')} ↗
                            </a>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                {/* Follow-up quick reply chips */}
                {msg.role === 'assistant' && msg.followUpQuestions && msg.followUpQuestions.length > 0 && (
                  <div className="followup-row">
                    {msg.spokenText && (
                      <button
                        type="button"
                        className="replay-voice-btn"
                        onClick={() => speakResponse(msg.spokenText!, msg.ttsLanguage || 'hi-IN')}
                      >
                        🔊 {t('Listen in Voice', 'आवाज़ में सुनें', 'Awaaz mein Sunein')}
                      </button>
                    )}
                  </div>
                )}
              </article>
            ))}

            {chatLoading && (
              <div className="chat-bubble assistant loading-bubble">
                <div className="spinner small-spinner" />
                <span>
                  {t(
                    'Evaluating deterministic scheme criteria...',
                    'सरकारी नियमों से पात्रता की जांच हो रही है...',
                    'Deterministic rules check ho rahe hain...'
                  )}
                </span>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          {/* Text Input Fallback Bar */}
          <form
            className="chat-input-bar"
            onSubmit={(e) => {
              e.preventDefault();
              sendChatMessage(chatInput, 'text');
            }}
          >
            <input
              type="text"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              placeholder={t(
                'Type in Hindi, Hinglish, or English (e.g., "Meri family income 1.5 lakh hai, main Rajasthan se hoon")...',
                'यहाँ हिंदी, हिंग्लिश या अंग्रेजी में लिखें (या ऊपर माइक दबाकर बोलें)...',
                'Hindi, Hinglish ya English mein likhein (ya Mic dabayein)...'
              )}
              aria-label="Ask about government welfare schemes"
            />
            <button
              type="submit"
              className="primary send-btn"
              disabled={!chatInput.trim() || chatLoading}
            >
              {t('Send', 'भेजें', 'Bhejein')} →
            </button>
          </form>

          <p className="trust-footer-note">
            🔒{' '}
            {t(
              'Trust & Transparency: AI never invents schemes or decides eligibility. All eligibility statuses come strictly from our deterministic rules engine verified against official government sources.',
              'पारदर्शिता: AI कभी स्वयं पात्रता तय नहीं करता। सभी परिणाम प्रकाशित सरकारी नियमों पर आधारित हैं।',
              'Trust Guarantee: Final eligibility hamesha deterministic rules engine se aati hai, AI kabhi fake schemes ya eligibility nahi banata.'
            )}
          </p>
        </div>
      </section>
    );
  }

  // -------------------------------------------------------------------------
  // PAGE: ENHANCED SCHEME DASHBOARD
  // -------------------------------------------------------------------------
  if (page === 'dashboard') {
    return shell(
      <section className="dashboard-page">
        <div className="dashboard-header">
          <div>
            <p className="eyebrow">DETERMINISTIC WELFARE SCHEME DASHBOARD</p>
            <h2>
              {t(
                'Explore & Filter Government Welfare Schemes',
                'सभी सरकारी कल्याणकारी योजनाएं और पात्रता स्थिति',
                'Sarkari Schemes aur Aapki Eligibility Dashboard'
              )}
            </h2>
            <p className="dashboard-sub">
              {t(
                'Every scheme below is evaluated deterministically against your profile and linked to its verified official portal.',
                'नीचे दी गई प्रत्येक योजना आपकी प्रोफ़ाइल के आधार पर जांची गई है और आधिकारिक सरकारी वेबसाइट से जुड़ी है।',
                'Har scheme aapki profile ke hisaab se deterministic rules se check ki gayi hai.'
              )}
            </p>
          </div>
          <div className="dashboard-cta">
            <button className="primary" onClick={() => go('voice')}>
              🎙️ {t('Ask Voice Assistant', 'बोलकर खोजें', 'Voice se Khojein')}
            </button>
          </div>
        </div>

        {/* Search & Status Tabs */}
        <div className="dashboard-controls">
          <input
            type="search"
            className="dashboard-search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t(
              'Search by scheme name, state (e.g., Rajasthan), student, women, housing...',
              'योजना का नाम, राज्य (जैसे Rajasthan), छात्रवृत्ति, महिला, आवास खोजें...',
              'Scheme ka naam, Rajasthan, scholarship, women, PM Awas search karein...'
            )}
          />
          <div className="filter-tabs" role="tablist">
            <button
              className={`filter-tab ${statusFilter === 'ALL' ? 'active' : ''}`}
              onClick={() => setStatusFilter('ALL')}
            >
              {t('All Schemes', 'सभी योजनाएं', 'All')} ({matches.length})
            </button>
            <button
              className={`filter-tab strong-tab ${statusFilter === 'likely_match' ? 'active' : ''}`}
              onClick={() => setStatusFilter('likely_match')}
            >
              ✓ {t('Eligible / Likely', 'पात्र (Likely)', 'Likely Eligible')} ({counts.likely})
            </button>
            <button
              className={`filter-tab possible-tab ${statusFilter === 'possible_match' ? 'active' : ''}`}
              onClick={() => setStatusFilter('possible_match')}
            >
              ◉ {t('Potentially Eligible', 'संभावित (Possible)', 'Potentially Eligible')} ({counts.possible})
            </button>
            <button
              className={`filter-tab no-tab ${statusFilter === 'not_match' ? 'active' : ''}`}
              onClick={() => setStatusFilter('not_match')}
            >
              × {t('Ineligible', 'अपात्र (Not Match)', 'Ineligible')} ({counts.notMatch})
            </button>
          </div>
        </div>

        {/* Scheme Cards Grid */}
        <div className="dashboard-grid">
          {filteredMatches.map((m) => {
            const [c, label] = statusBadge(m.result.status);
            return (
              <article className="scheme dashboard-scheme-card" key={m.scheme.id}>
                <div className="scheme-top">
                  <span className={`pill ${c}`}>{label}</span>
                  <small className="verified-tag">
                    ✓ Verified: {m.scheme.source_verified_at} · {m.scheme.state_scope || 'India'}
                  </small>
                </div>
                <h3>{m.scheme.name}</h3>
                <p className="scheme-desc">{m.scheme.short_description}</p>
                <div className="benefit-banner">
                  <span>{t('Benefit:', 'लाभ:', 'Benefit:')}</span>
                  <b>{m.scheme.benefit_amount}</b>
                </div>

                <div className="rule-mini-list">
                  {m.result.matched.length > 0 && (
                    <p className="mini-match">
                      <b>✓ {t('Matches:', 'मिलान:', 'Matched:')}</b> {m.result.matched.join(' · ')}
                    </p>
                  )}
                  {m.result.missing.length > 0 && (
                    <p className="mini-missing">
                      <b>! {t('To confirm:', 'पुष्टि बाकी:', 'Missing Info:')}</b> {m.result.missing.join(' · ')}
                    </p>
                  )}
                  {m.result.unmatched.length > 0 && (
                    <p className="mini-unmatched">
                      <b>× {t('Does not match:', 'मेल नहीं:', 'Unmatched:')}</b> {m.result.unmatched.join(' · ')}
                    </p>
                  )}
                </div>

                <div className="doc-preview">
                  <small>
                    <b>📄 {t('Required Documents:', 'आवश्यक दस्तावेज़:', 'Documents:')}</b>{' '}
                    {m.scheme.required_documents.join(', ')}
                  </small>
                </div>

                <footer>
                  <a
                    href={m.scheme.official_source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="official-link"
                  >
                    {t('Official Source', 'आधिकारिक स्रोत', 'Official Portal')} ↗
                  </a>
                  <div className="card-btn-group">
                    <button
                      type="button"
                      className="secondary"
                      onClick={() =>
                        speakResponse(
                          `${m.scheme.name}. ${m.scheme.benefit_summary}. Benefit amount: ${m.scheme.benefit_amount}.`,
                          lang === 'EN' ? 'en-IN' : 'hi-IN'
                        )
                      }
                    >
                      🔊 {t('Listen', 'सुनें', 'Sunein')}
                    </button>
                    <button
                      type="button"
                      className="primary"
                      onClick={() => handleExplainScheme(m)}
                    >
                      {t('Full Details & Apply', 'विवरण और आवेदन', 'Details & Apply')} →
                    </button>
                  </div>
                </footer>
              </article>
            );
          })}
        </div>
      </section>
    );
  }

  // -------------------------------------------------------------------------
  // PAGE: HOME (LANDING PAGE WITH VOICE-FIRST CTA & SYNTHETIC PERSONAS)
  // -------------------------------------------------------------------------
  if (page === 'home')
    return shell(
      <>
        <section className="hero">
          <p className="eyebrow">GNANI AI VOICE × DETERMINISTIC CITIZEN WELFARE PLATFORM</p>
          <h1>
            {t(
              'Your Voice. Your Rights. Your Schemes.',
              'आपकी आवाज़। आपका अधिकार। आपकी योजनाएं।',
              'Aapki Awaaz. Aapka Adhikaar. Aapki Schemes.'
            )}
          </h1>
          <p>
            {t(
              'Speak naturally in Hindi, Hinglish, or English to discover verified Indian government welfare schemes, check exact deterministic eligibility, and prepare required documents.',
              'हिंदी, हिंग्लिश या अंग्रेजी में बोलकर सरकारी कल्याणकारी योजनाएं खोजें, पात्रता समझें और आवेदन के लिए आवश्यक दस्तावेज़ तैयार करें।',
              'Hindi, Hinglish ya English mein bolkar apne liye sahi sarkari schemes khojein, eligibility rules samjhein aur zaroori documents tayyar karein.'
            )}
          </p>
          <div className="actions">
            <button className="primary hero-voice-btn" onClick={() => go('voice')}>
              🎙️ {t('Start Voice Discovery (Gnani AI)', 'बोलकर योजनाएं खोजें (Gnani AI)', 'Bolkar Schemes Khojein (Gnani AI)')} <b>→</b>
            </button>
            <button className="secondary" onClick={() => go('goal')}>
              {t('Step-by-step Questionnaire', 'प्रश्नावली से खोजें', 'Step-by-Step Check')}
            </button>
            <button className="secondary" onClick={() => go('dashboard')}>
              📋 {t('Browse All Schemes', 'सभी योजनाएं देखें', 'All Schemes Dashboard')}
            </button>
          </div>
          <p className="trust">
            ◉{' '}
            {t(
              'Independent citizen welfare prototype • Powered by Gnani AI Speech APIs & Deterministic Eligibility Rules • Not an official government website',
              'स्वतंत्र नागरिक प्रोटोटाइप • Gnani AI वॉइस और नियम इंजन द्वारा संचालित • आधिकारिक सरकारी वेबसाइट नहीं',
              'Independent prototype • Gnani AI Voice + Deterministic Eligibility Rules • Official government decision nahi hai'
            )}
          </p>
        </section>

        <section className="demo">
          <h2>{t('Try a synthetic demo profile or voice scenario', 'एक सिंथेटिक डेमो प्रोफ़ाइल आज़माएं', 'Demo Profile ya Voice Scenario Try Karein')}</h2>
          <div className="demo-grid">
            <button onClick={() => loadDemo('student')}>
              🎓 <b>Aarav</b>
              <small>Student · Rajasthan (₹2.4L)</small>
            </button>
            <button onClick={() => loadDemo('woman')}>
              👩 <b>Meera</b>
              <small>Technical student · UP (OBC)</small>
            </button>
            <button onClick={() => loadDemo('mother')}>
              🤰 <b>Nisha</b>
              <small>Pregnancy support · Bihar</small>
            </button>
          </div>
        </section>

        <section id="how" className="steps">
          <article>
            <span>01</span>
            <h3>SPEAK IN YOUR LANGUAGE</h3>
            <p>
              {t(
                'Ask in Hindi, Hinglish, or English using Gnani AI Prisma v3.0 Speech-to-Text.',
                'Gnani AI Prisma वॉइस की मदद से अपनी भाषा में बोलकर सवाल पूछें।',
                'Gnani AI Prisma v3.0 ke saath Hindi, Hinglish ya English mein bolein.'
              )}
            </p>
          </article>
          <article>
            <span>02</span>
            <h3>DETERMINISTIC ELIGIBILITY</h3>
            <p>
              {t(
                'Our rule engine checks published criteria—AI never fabricates schemes or eligibility.',
                'हमारा नियम इंजन प्रकाशित सरकारी मानदंडों से सटीक मिलान करता है।',
                'Hamara deterministic engine asli government rules check karta hai.'
              )}
            </p>
          </article>
          <article>
            <span>03</span>
            <h3>PREPARE & LISTEN</h3>
            <p>
              {t(
                'Hear explanations via Gnani Timbre v2.5 TTS and check required documents before applying.',
                'Gnani Timbre वॉइस में जानकारी सुनें और आवश्यक दस्तावेज़ तैयार करें।',
                'Gnani Timbre v2.5 voice mein jawab sunein aur documents checklist dekhein.'
              )}
            </p>
          </article>
        </section>
      </>
    );

  // -------------------------------------------------------------------------
  // EXISTING GUIDED FLOW PAGES (PRESERVED & ENHANCED)
  // -------------------------------------------------------------------------
  if (page === 'goal')
    return shell(
      <section className="flow">
        <p className="eyebrow">STEP 1 OF 3</p>
        <h2>{t('What are you trying to achieve?', 'आप क्या करना चाहते हैं?', 'Aap kya hasil karna chahte hain?')}</h2>
        <div className="goalgrid">
          {[
            ['🎓', 'Pay for my education'],
            ['👩', 'Find support available to me'],
            ['🤰', 'Support for pregnancy or motherhood'],
            ['👧', 'Support for a girl child'],
            ['🏠', 'Housing support (PM Awas Yojana)'],
            ['🔎', "I'm not sure - help me explore"],
          ].map(([icon, label]) => (
            <button
              key={label}
              onClick={() => {
                setGoal(label);
                go('questions');
              }}
            >
              <span>{icon}</span>
              {label}
            </button>
          ))}
        </div>
        <label>
          {t('Or tell us in your own words', 'या अपने शब्दों में बताएं', 'Ya apne shabdon mein batayein')}
          <textarea
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="Mujhe college ki fees ke liye scholarship chahiye..."
          />
        </label>
        <div className="actions">
          <button className="secondary" onClick={() => go('voice')}>
            🎙️ {t('Use Voice Assistant Instead', 'बोलकर बताएं', 'Voice Assistant Use Karein')}
          </button>
          <button className="primary" disabled={!goal} onClick={() => go('questions')}>
            {t('Continue', 'आगे बढ़ें', 'Continue')} →
          </button>
        </div>
      </section>
    );

  if (page === 'questions') {
    const [field, label, type] = current;
    const isSelect = type.startsWith('select:');
    return shell(
      <section className="flow question">
        <p className="eyebrow">
          STEP 2 OF 3 · {i + 1}/{questions.length}
        </p>
        <div className="progress">
          <i style={{ width: `${((i + 1) / questions.length) * 100}%` }} />
        </div>
        <h2>{label}</h2>
        <p className="why">
          ⓘ{' '}
          {t(
            'Why we ask: some schemes use this information to compare published criteria.',
            'हम क्यों पूछते हैं: कुछ योजनाएं प्रकाशित मानदंडों की तुलना के लिए यह जानकारी उपयोग करती हैं।',
            'Yeh jankari published scheme rules se compare karne ke kaam aati hai.'
          )}
        </p>
        {isSelect ? (
          <select
            aria-label={label}
            value={
              field === 'other_scholarship'
                ? profile[field] === true
                  ? 'Yes'
                  : profile[field] === false
                  ? 'No'
                  : ''
                : profile[field] || ''
            }
            onChange={(e) =>
              setProfile({
                ...profile,
                [field]: field === 'other_scholarship' ? e.target.value === 'Yes' : e.target.value,
              })
            }
          >
            <option value="">{t('Choose an option', 'एक विकल्प चुनें', 'Option chunein')}</option>
            {type
              .slice(7)
              .split('|')
              .map((x) => (
                <option key={x}>{x}</option>
              ))}
          </select>
        ) : (
          <input
            aria-label={label}
            type="number"
            value={profile[field] ?? ''}
            onChange={(e) => setProfile({ ...profile, [field]: Number(e.target.value) })}
          />
        )}
        <div className="actions">
          <button className="secondary" disabled={!i} onClick={() => setI(i - 1)}>
            {t('Back', 'पीछे', 'Back')}
          </button>
          <button
            className="primary"
            disabled={profile[field] === undefined || profile[field] === ''}
            onClick={next}
          >
            {i === questions.length - 1
              ? t('Review profile', 'प्रोफ़ाइल देखें', 'Review Profile')
              : t('Next', 'अगला', 'Next')}{' '}
            →
          </button>
        </div>
      </section>
    );
  }

  if (page === 'summary')
    return shell(
      <section className="flow">
        <p className="eyebrow">STEP 3 OF 3</p>
        <h2>{t("Here's what we understood", 'हमने यह समझा', 'Humne yeh samjha')}</h2>
        <div className="profile-card">
          <p className="goal-text">“{goal}”</p>
          {Object.entries(profile)
            .filter(([k]) => !['name', 'other_scholarship'].includes(k))
            .map(([k, v]) => (
              <div key={k}>
                <span>{formatFieldLabel(k)}</span>
                <b>{formatFieldValue(k, v)}</b>
              </div>
            ))}
        </div>
        <p className="notice">
          🔒{' '}
          {t(
            'This is synthetic demo information. We never ask for Aadhaar, PAN, OTP, bank details or passwords.',
            'यह सिंथेटिक डेमो जानकारी है। हम कभी आधार, पैन, OTP, बैंक विवरण या पासवर्ड नहीं मांगते।',
            'Yeh demo jankari hai. Hum kabhi Aadhaar, PAN, OTP ya bank details nahi maangte.'
          )}
        </p>
        <div className="actions">
          <button className="secondary" onClick={() => go('questions')}>
            {t('Edit', 'बदलें', 'Edit')}
          </button>
          <button className="primary" onClick={match}>
            {t('Find my benefits', 'मेरे लाभ खोजें', 'Find My Schemes')} →
          </button>
        </div>
      </section>
    );

  if (page === 'loading')
    return shell(
      <section className="flow loading">
        <div className="spinner" />
        <h2>{t('Checking published criteria…', 'प्रकाशित मानदंड देख रहे हैं…', 'Published rules check ho rahe hain...')}</h2>
        <p>
          {t(
            'The eligibility engine is running locally. AI never decides eligibility.',
            'पात्रता इंजन स्थानीय रूप से चल रहा है। AI पात्रता तय नहीं करता।',
            'Eligibility engine deterministic rules chala raha hai. AI eligibility decide nahi karta.'
          )}
        </p>
      </section>
    );

  if (page === 'results')
    return shell(
      <section className="results">
        <p className="eyebrow">YOUR OPTIONS</p>
        <h2>
          {t(
            'Here are the options that look most relevant.',
            'ये विकल्प सबसे अधिक प्रासंगिक लगते हैं।',
            'Aapke liye sabse relevant government schemes'
          )}
        </h2>
        <p>
          {t(
            'Assessment based on the information you shared and published rules.',
            'आपके उत्तर और प्रकाशित नियमों पर आधारित मूल्यांकन।',
            'Aapki details aur published government rules par aadharit results.'
          )}
        </p>
        {matches.map((m) => {
          const [c, label] = statusBadge(m.result.status);
          return (
            <article className="scheme" key={m.scheme.id}>
              <div className="scheme-top">
                <span className={`pill ${c}`}>{label}</span>
                <small>Source verified: {m.scheme.source_verified_at}</small>
              </div>
              <h3>{m.scheme.name}</h3>
              <p>{m.scheme.benefit_summary}</p>
              <p className="benefit-highlight">{m.scheme.benefit_amount}</p>
              <p className="reason">
                {m.result.status === 'not_match'
                  ? m.result.unmatched[0] || 'Some published criteria do not match'
                  : m.result.matched.slice(0, 2).join(' · ') || 'We need more details to check'}
              </p>
              <footer>
                <span>{m.scheme.application_status}</span>
                <button className="secondary" onClick={() => handleExplainScheme(m)}>
                  {m.result.status === 'not_match'
                    ? t("Why doesn't it fit?", 'यह क्यों नहीं फिट है?', 'Kyun fit nahi hai?')
                    : t('See why & apply', 'कारण और आवेदन देखें', 'See Why & Apply')}{' '}
                  →
                </button>
              </footer>
            </article>
          );
        })}
      </section>
    );

  if (page === 'detail' && selected) {
    const r = selected.result;
    const [c, label] = statusBadge(r.status);
    return shell(
      <section className="flow detail">
        <button className="backlink" onClick={() => go('dashboard')}>
          ← {t('All schemes', 'सभी योजनाएं', 'All Schemes')}
        </button>
        <div className="detail-top-row">
          <span className={`pill ${c}`}>{label}</span>
          <button
            type="button"
            className="secondary small-btn"
            onClick={() =>
              speakResponse(
                aiExplanation ||
                  `${selected.scheme.name}. ${selected.scheme.benefit_summary}. Required documents: ${selected.scheme.required_documents.join(', ')}`,
                lang === 'EN' ? 'en-IN' : 'hi-IN'
              )
            }
          >
            🔊 {t('Read Aloud (Gnani TTS)', 'आवाज़ में सुनें (Gnani TTS)', 'Listen via Gnani TTS')}
          </button>
        </div>
        <h2>{selected.scheme.name}</h2>
        <p className="lead">{selected.scheme.benefit_summary} — <b>{selected.scheme.benefit_amount}</b></p>

        {/* AI Explanation Card clearly separated from Deterministic Verification */}
        <div className="ai-explanation-box">
          <div className="ai-box-tag">
            <span>🤖 AI Citizen Summary (Explanatory Only)</span>
            <small>Does not alter deterministic status</small>
          </div>
          <p>
            {explaining
              ? 'Generating citizen-friendly explanation...'
              : aiExplanation ||
                (r.status === 'likely_match'
                  ? 'Your shared profile matches all published rules checked for this scheme.'
                  : r.status === 'possible_match'
                  ? 'You match the initial criteria, but a few remaining profile details need to be confirmed.'
                  : 'One or more published eligibility rules do not match your current profile.')}
          </p>
        </div>

        <div className="criteria">
          <div>
            <h3>✓ {t('Matched Published Criteria', 'मिलान हुए नियम', 'Matched Criteria')}</h3>
            {r.matched.length ? (
              r.matched.map((x) => <p key={x}>✓ {x}</p>)
            ) : (
              <p>{t('None confirmed yet', 'अभी कोई पुष्टि नहीं', 'Abhi confirm nahi hua')}</p>
            )}
          </div>
          {r.unmatched.length > 0 && (
            <div className="bad">
              <h3>× {t('Does Not Match', 'मिलान नहीं', 'Unmatched Criteria')}</h3>
              {r.unmatched.map((x) => (
                <p key={x}>× {x}</p>
              ))}
            </div>
          )}
          {r.missing.length > 0 && (
            <div className="warn">
              <h3>! {t('Need to Confirm', 'पुष्टि जरूरी', 'Missing Criteria to Check')}</h3>
              {r.missing.map((x) => (
                <p key={x}>! {x}</p>
              ))}
            </div>
          )}
        </div>

        <div className="detail-steps-card">
          <h3>📋 {t('Official Application Procedure', 'आवेदन की प्रक्रिया', 'Application Steps')}</h3>
          <ol>
            {selected.scheme.application_steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </div>

        <aside className="source">
          {t('Official Verification & Trust:', 'आधिकारिक सत्यापन:')}{' '}
          {t(
            'We compare the answers you share against explicit published rules. This is an informational assessment, not an official government decision or guarantee of benefit.',
            'हम आपके उत्तरों की स्पष्ट प्रकाशित नियमों से तुलना करते हैं। यह आधिकारिक सरकारी निर्णय या लाभ की गारंटी नहीं है।',
            'Yeh informational assessment published government rules par aadharit hai, official guarantee nahi.'
          )}{' '}
          <a href={selected.scheme.official_source_url} target="_blank" rel="noreferrer">
            {t('View official government portal', 'आधिकारिक सरकारी पोर्टल देखें', 'View Official Portal')} ({selected.scheme.official_source_url}) ↗
          </a>
        </aside>

        <div className="actions">
          {r.status === 'not_match' ? (
            <button className="primary" onClick={() => go('dashboard')}>
              {t('Explore alternatives', 'अन्य विकल्प देखें', 'Explore Alternatives')} →
            </button>
          ) : (
            <button className="primary" onClick={() => go('documents')}>
              {t('Prepare required documents', 'दस्तावेज़ों की तैयारी करें', 'Prepare Documents')} →
            </button>
          )}
        </div>
      </section>
    );
  }

  if (page === 'documents' && selected) {
    const total = selected.scheme.required_documents.length;
    const done = Object.values(docs).filter(Boolean).length;
    return shell(
      <section className="flow">
        <p className="eyebrow">READINESS</p>
        <h2>{t('You may need these documents', 'आपको इन दस्तावेज़ों की आवश्यकता हो सकती है', 'Zaroori Documents Checklist')}</h2>
        <p>
          {t(
            'Use demo documents only. Never upload sensitive documents to this prototype.',
            'केवल डेमो दस्तावेज़ों का उपयोग करें। इस प्रोटोटाइप पर संवेदनशील दस्तावेज़ अपलोड न करें।',
            'Sirf demo checklist use karein. Asli personal documents upload na karein.'
          )}
        </p>
        <div className="checklist">
          {selected.scheme.required_documents.map((d) => (
            <label key={d}>
              <input
                type="checkbox"
                checked={!!docs[d]}
                onChange={(e) => setDocs({ ...docs, [d]: e.target.checked })}
              />
              <span>{docs[d] ? '✓' : '○'}</span>
              {d}
              <button
                type="button"
                className="demo-doc"
                onClick={() => setDocs({ ...docs, [d]: true })}
              >
                {t('Use demo document', 'डेमो दस्तावेज़', 'Use Demo Doc')}
              </button>
            </label>
          ))}
        </div>
        <div className="readiness">
          <b>{Math.round((done / total) * 100)}%</b>
          <span>
            {done} {t(`of ${total} requirements ready`, `में से ${total} आवश्यकताएं तैयार`, `of ${total} ready`)}
          </span>
          <i>
            <em style={{ width: `${(done / total) * 100}%` }} />
          </i>
        </div>
        <button className="primary" onClick={() => go('application')}>
          {t('Complete application', 'आवेदन पूरा करें', 'Continue to Mock Application')} →
        </button>
      </section>
    );
  }

  if (page === 'application')
    return shell(
      <section className="flow">
        <p className="eyebrow">MOCK APPLICATION · 1 OF 4</p>
        <h2>{t('Almost ready to apply', 'आवेदन के लिए लगभग तैयार', 'Application ke liye tayyar')}</h2>
        <div className="appsteps">
          <span>✓ {t('Personal details', 'व्यक्तिगत जानकारी', 'Personal details')}</span>
          <span>✓ {t('Education / benefit details', 'शिक्षा / लाभ विवरण', 'Benefit details')}</span>
          <span>✓ {t('Demo documents', 'डेमो दस्तावेज़', 'Demo documents')}</span>
          <span>● {t('Review', 'समीक्षा', 'Review')}</span>
        </div>
        <h3>{t('Prototype consistency check', 'प्रोटोटाइप संगतता जांच', 'Consistency Check')}</h3>
        <p>
          {t(
            'Your mock details and demo documents are consistent. This is not official verification.',
            'आपके मॉक विवरण और डेमो दस्तावेज़ संगत हैं। यह आधिकारिक सत्यापन नहीं है।',
            'Aapke mock details aur checklist consistent hain.'
          )}
        </p>
        <button className="primary" onClick={submit}>
          {t('Submit demo application', 'डेमो आवेदन जमा करें', 'Submit Demo Application')} →
        </button>
      </section>
    );

  return shell(
    <section className="flow tracker">
      <p className="eyebrow">DEMO APPLICATION</p>
      <div className="success">✓</div>
      <h2>{t('Application submitted', 'आवेदन जमा किया गया', 'Demo Application Submitted')}</h2>
      <p className="application-id">{appId || 'MA-2026-4821'}</p>
      <p className="notice">
        {t(
          'Demo application - no government application was submitted.',
          'डेमो आवेदन - कोई सरकारी आवेदन जमा नहीं किया गया।',
          'Demo application - koi official sarkari form submit nahi hua hai.'
        )}
      </p>
      <div className="timeline">
        <p>
          <b>✓</b> {t('Application submitted', 'आवेदन जमा किया गया')}
        </p>
        <p>
          <b>✓</b> {t('Documents checked', 'दस्तावेज़ जांचे गए')}
        </p>
        <p className="active">
          <b>●</b> {t('Verification', 'सत्यापन')}
        </p>
        <p>
          <b>○</b> {t('Officer review', 'अधिकारी समीक्षा')}
        </p>
        <p>
          <b>○</b> {t('Decision', 'निर्णय')}
        </p>
      </div>
      <h3>{t('What happens now?', 'अब क्या होगा?')}</h3>
      <p>
        {t(
          'Your application has been submitted in this prototype. In a real implementation, the next step would depend on the relevant government department.',
          'आपका आवेदन इस प्रोटोटाइप में जमा हो गया है। असली प्रक्रिया में अगला कदम संबंधित विभाग पर निर्भर होगा।'
        )}
      </p>
      <button className="primary" onClick={() => go('home')}>
        {t('My benefits journey', 'मेरी लाभ यात्रा')} →
      </button>
    </section>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
