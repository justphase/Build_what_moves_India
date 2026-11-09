/**
 * Audio recording and WAV encoding utilities for Gnani AI Prisma v3.0 STT (/stt/v3).
 * Converts recorded browser audio into 16kHz 16-bit mono linear PCM WAV format,
 * which is natively supported by https://api.vachana.ai/stt/v3.
 */

export function encodeWavFromAudioBuffer(audioBuffer: AudioBuffer, targetSampleRate = 16000): Blob {
  const numChannels = 1;
  const sourceRate = audioBuffer.sampleRate;
  const rawData = audioBuffer.getChannelData(0);

  // Downsample or resample to targetSampleRate (16kHz mono)
  const ratio = sourceRate / targetSampleRate;
  const newLength = Math.max(1, Math.round(rawData.length / ratio));
  const samples = new Int16Array(newLength);

  for (let i = 0; i < newLength; i++) {
    const srcIdx = Math.min(rawData.length - 1, Math.floor(i * ratio));
    const clamped = Math.max(-1, Math.min(1, rawData[srcIdx]));
    samples[i] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;
  }

  const byteRate = targetSampleRate * numChannels * 2;
  const blockAlign = numChannels * 2;
  const dataByteLength = samples.length * 2;
  const buffer = new ArrayBuffer(44 + dataByteLength);
  const view = new DataView(buffer);

  const writeStr = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  };

  // RIFF WAVE header
  writeStr(0, 'RIFF');
  view.setUint32(4, 36 + dataByteLength, true);
  writeStr(8, 'WAVE');
  writeStr(12, 'fmt ');
  view.setUint32(16, 16, true); // PCM chunk size
  view.setUint16(20, 1, true);  // Linear PCM format = 1
  view.setUint16(22, numChannels, true);
  view.setUint32(24, targetSampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, 16, true); // 16-bit samples
  writeStr(36, 'data');
  view.setUint32(40, dataByteLength, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i++, offset += 2) {
    view.setInt16(offset, samples[i], true);
  }

  return new Blob([buffer], { type: 'audio/wav' });
}

export async function convertBlobToWav(blob: Blob): Promise<Blob> {
  try {
    const arrayBuffer = await blob.arrayBuffer();
    const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new AudioCtx();
    try {
      const decoded = await ctx.decodeAudioData(arrayBuffer);
      return encodeWavFromAudioBuffer(decoded, 16000);
    } finally {
      await ctx.close().catch(() => {});
    }
  } catch {
    // If browser decode fails, return original blob
    return blob;
  }
}

