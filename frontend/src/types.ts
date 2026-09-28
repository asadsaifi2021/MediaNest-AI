export type MediaType = "image" | "video" | "audio";
export interface Media {
  id: string;
  user_id: string;
  device_id: string;
  local_file_id: string;
  original_filename?: string | null;
  file_type: MediaType;
  thumbnail_url: string | null;
  tags: string[];
  ai_tags?: string[];
  ai_status?: string;
  ai_message?: string | null;
  media_info?: {
    duration?: number;
    width?: number;
    height?: number;
    video_codec?: string;
    audio_codec?: string;
  };
  transcription: string | null;
  created_at: string;
  updated_at: string;
}
export interface MediaPage {
  results: Media[];
  has_more: boolean;
}
export interface FaceMatch {
  media_id: string;
  face_id: string;
  person_name: string | null;
  similarity: number;
}
export interface ArchiveEvent {
  id: string;
  event_type: string;
  device_id: string;
  occurred_at: string;
  asset_id: string;
}
