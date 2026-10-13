"""Shared audio budget from download through preparation, preview and verification."""

# Keep input/download and produced/served audio within the same byte budget.
MAX_AUDIO_BYTES = 64 * 1024 * 1024
# Existing MoviePilot upload request contract, independent of generated media.
MAX_UPLOAD_BYTES = 32 * 1024 * 1024
STREAM_CHUNK_BYTES = 256 * 1024


class AudioSizeLimitError(ValueError):
    """A complete track cannot fit the supported media budget; never truncate it."""
