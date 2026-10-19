"""Hub 当前承担同步或持久化的来源范围。"""

SOURCE_KINDS = {
    'skysight': frozenset(('computer_segment', 'computer_segment_invalid', 'computer_summary')),
    'plaud': frozenset(('recording', 'recording_transcript', 'recording_daily_report',
                        'recording_summary', 'recording_processing_status', 'recording_artifact')),
}


def validate_sources(config):
    for source, settings in config['sources'].items():
        if settings['adapter'] not in SOURCE_KINDS:
            raise ValueError(f'unsupported_source_adapter: {source}')
