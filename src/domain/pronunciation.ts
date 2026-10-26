/** Stable application port; independent of the acoustic model and HTTP transport. */
export type PronunciationTarget = Readonly<{
  id: string;
  pinyin: string;
  task: 'syllable' | 'initial' | 'final' | 'blend' | 'sequence';
}>;

export type PronunciationRequest = Readonly<{
  requestId: string;
  targetId: string;
  /** In-memory 16kHz mono PCM16 WAV. The mock deliberately does not decode it. */
  audio: Blob;
  signal?: AbortSignal;
}>;

type ResultContext = Readonly<{
  contractVersion: 1;
  requestId: string;
  targetId: string;
  evidence: 'mock' | 'acoustic' | 'none';
  toneAssessed: boolean;
}>;

export type PronunciationFailureReason =
  | 'unsupported-target'
  | 'not-configured'
  | 'invalid-audio'
  | 'insufficient-evidence'
  | 'model-unavailable'
  | 'timeout'
  | 'busy'
  | 'network-error';

export type PronunciationMatchResult = ResultContext &
  (
    | Readonly<{ status: 'matched' | 'retry'; reason: null }>
    | Readonly<{
        status: 'uncertain' | 'unavailable';
        reason: PronunciationFailureReason;
      }>
  );

export type PronunciationRecognitionResult = ResultContext &
  (
    | Readonly<{ status: 'recognized'; recognizedPinyin: string; reason: null }>
    | Readonly<{
        status: 'uncertain' | 'unavailable';
        recognizedPinyin: null;
        reason: PronunciationFailureReason;
      }>
  );

export interface PronunciationService {
  match(request: PronunciationRequest): Promise<PronunciationMatchResult>;
  recognize(request: PronunciationRequest): Promise<PronunciationRecognitionResult>;
}
