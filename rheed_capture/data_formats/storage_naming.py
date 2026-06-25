SEQUENCE_DIR_PATTERN = "image_{number:03d}"
ANGLE_SCAN_DIR_PATTERN = "angle_scan_{number:03d}"
RECORDING_DIR_PATTERN = "record-{number}"

SEQUENCE_TIFF_FILENAME_PATTERN = (
    "{experiment_dir_name}-{sequence_number}_"
    "expo{exposure_ms:g}_gain{gain:g}.tiff"
)

ANGLE_DIR_PATTERN = "angle{angle_deg:+06.1f}"

ANGLE_SCAN_TIFF_FILENAME_PATTERN = (
    "{scan_id}_angle{angle_deg:+06.1f}_"
    "exp{exposure_ms:g}_gain{gain:g}.tiff"
)

RECORDING_TIFF_FILENAME_PATTERN = (
    "{sample_name}_{date}_rec-{record_number}_{frame_index:05d}.tiff"
)

SEQUENCE_TIFF_COMPRESSION = None
ANGLE_SCAN_TIFF_COMPRESSION = None
RECORDING_TIFF_COMPRESSION = "zlib"

RECORDING_SAVE_QUEUE_MAX_SIZE = 8
