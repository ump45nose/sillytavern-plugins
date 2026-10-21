"""Archive acknowledgement through Hermes' existing non-agent delivery command."""
import subprocess

from review.observability import StructuredLogger


class ArchiveNotifier:
    def __init__(self, config, runner=subprocess.run):
        self.config, self.runner = config, runner
        self.logger = StructuredLogger(config.path('REVIEW_LOG_DIR'))

    def __call__(self, kind, label):
        title = {'daily':'日报','weekly':'周报','stage':'阶段结案'}[kind]
        command = [self.config.values['REVIEW_HERMES_BIN'],'-p',self.config.values['REVIEW_HERMES_PROFILE'],
                   'send','--to',self.config.values['REVIEW_DELIVERY_TARGET'],'--quiet']
        error_type=None
        try:
            result=self.runner(command,input=f'{label} {title}已在 App 归档',text=True,
                               capture_output=True,timeout=20,check=False)
            if result.returncode: raise RuntimeError('delivery_failed')
        except Exception as error:
            error_type=type(error).__name__
        self.logger.emit('review.app_archive_notification','failed' if error_type else 'sent',
                         kind=kind,error_type=error_type)
