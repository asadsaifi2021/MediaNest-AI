import type { Media } from "./types";

// Deliberately synthetic metadata and bundled illustrations; never mixed with user data.
const entries: [string, Media["file_type"], string[], string, string | null][] =
  [
    [
      "The quiet side of the lake.jpg",
      "image",
      ["Nature", "Mountains", "Travel"],
      "lake",
      null,
    ],
    [
      "A little further from home.mp4",
      "video",
      ["Travel", "Road trip"],
      "road",
      null,
    ],
    ["Sunday, slowly.jpg", "image", ["Home", "Garden"], "garden", null],
    [
      "Stories around the table.m4a",
      "audio",
      ["Family", "Stories"],
      "audio",
      "Sample transcript: We used to take the long road to the lake. Everyone had a favourite song for the journey.",
    ],
    [
      "Where the forest begins.jpg",
      "image",
      ["Nature", "Forest"],
      "forest",
      null,
    ],
    ["Golden hour, saved.jpg", "image", ["Travel", "Sunset"], "sunset", null],
  ];
export const sampleMedia: Media[] = entries.map(
  ([name, file_type, tags, art, transcription], i) => ({
    id: `sample-${i + 1}`,
    user_id: "sample",
    device_id: "Example home storage",
    local_file_id: name,
    file_type,
    tags,
    transcription,
    thumbnail_url: `/samples/${art}.svg`,
    created_at: `2026-09-${String(24 - i).padStart(2, "0")}T12:00:00Z`,
    updated_at: `2026-09-${String(24 - i).padStart(2, "0")}T12:00:00Z`,
  }),
);
