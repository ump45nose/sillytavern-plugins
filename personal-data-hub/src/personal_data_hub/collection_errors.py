"""Safe collection diagnostics for retained source run records."""

REASONS = {
    'collector_busy': '该来源正在采集或写入，稍后自动重试',
    'plaud_sync_failed': 'Plaud 同步进程执行失败',
    'plaud_recording_missing': 'Plaud 录音文件缺失',
}


def error_detail(exc):
    kind = type(exc).__name__
    message = str(exc)
    reason = REASONS.get(message)
    if not reason:
        if isinstance(exc, BaseExceptionGroup):
            details = [error_detail(child) for child in exc.exceptions[:5]]
            return {"type": kind, "reason": "；".join(dict.fromkeys(d['reason'] for d in details)),
                    "causes": details}
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if kind == "HTTPError":
            status = getattr(exc, "code", None)
        if isinstance(status, int) and 100 <= status <= 599:
            reason = f"来源接口请求失败（HTTP {status}）"
        elif isinstance(exc, PermissionError):
            reason = "读取来源数据的权限不足"
        elif isinstance(exc, FileNotFoundError):
            reason = "采集所需的文件或程序不存在"
        elif isinstance(exc, TimeoutError) or kind in ("TimeoutExpired", "ConnectTimeout", "ReadTimeout", "PoolTimeout"):
            reason = "采集请求超时"
        elif isinstance(exc, ConnectionError) or kind in ("URLError", "ConnectError", "ReadError", "RemoteProtocolError"):
            reason = "来源服务网络连接失败或中断"
        elif kind == "OperationalError":
            reason = "数据库连接或操作失败"
        else:
            reason = "采集器执行失败，未提供可识别的具体原因"
    return {"type": kind, "reason": reason}
