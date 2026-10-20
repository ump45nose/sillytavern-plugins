from mcp_platform import authorize, create_server

from .models import Bill, HealthDay


def create_mcp(service, runtime):
    server = create_server(runtime, instructions=(
        "健康以北京时间每日记录管理，账单逐张管理。支持完整增删改查、日期筛选与汇总。"
        "汇总日期包含起止日；缺失不补零，币种分别统计。"
        "健康 PATCH 替换提交的数组，省略字段保持原值，null 删除该指标。"
        "金额使用十进制字符串。修改立即生效，来源后续上传可再次更新或创建记录。"))
    read, write = authorize("read", runtime), authorize("write", runtime)

    @server.tool(auth=read)
    def list_health_days(start_date: str | None = None, end_date: str | None = None, offset: int = 0, limit: int = 50) -> dict:
        """分页列出健康日概览；不返回心率等完整数组。"""
        return service.list_health_days(start_date, end_date, offset, limit)

    @server.tool(auth=read)
    def get_health_day(date: str) -> dict:
        """读取指定日期的完整健康业务记录，包含平铺时间数组。"""
        return service.get_health_day(date)

    @server.tool(auth=write)
    def create_health_day(record: HealthDay) -> dict:
        """创建一天的健康记录；日期已存在时报冲突。"""
        return service.create_health_day(record.model_dump(exclude_none=True))

    @server.tool(auth=write)
    def update_health_day(date: str, patch: dict) -> dict:
        """修改健康日字段；数组整体替换，null 删除指标，date 不可修改。"""
        return service.update_health_day(date, patch)

    @server.tool(auth=write)
    def delete_health_day(date: str) -> dict:
        """删除整天健康记录；后续来源上传可重新创建。"""
        return service.delete_health_day(date)

    @server.tool(auth=read)
    def summarize_health(start_date: str, end_date: str, metrics: list[str] | None = None) -> dict:
        """汇总任意日期区间内的指定健康指标；缺失为 null。"""
        return service.health_summary(start_date, end_date, metrics)

    @server.tool(auth=read)
    def list_bills(start_date: str | None = None, end_date: str | None = None, type: str | None = None,
                   currency: str | None = None, category: str | None = None, book: str | None = None,
                   account: str | None = None, account_from: str | None = None, account_to: str | None = None,
                   status: str | None = None, query: str | None = None, offset: int = 0, limit: int = 50) -> dict:
        """分页筛选账单；query 检索商家、商品和备注，默认包含待确认。"""
        return service.list_bills(start_date=start_date, end_date=end_date, type=type, currency=currency,
            category=category, book=book, account=account, account_from=account_from, account_to=account_to,
            status=status, query=query, offset=offset, limit=limit)

    @server.tool(auth=read)
    def get_bill(id: str) -> dict:
        """按本地 UUID 读取账单。"""
        return service.get_bill(id)

    @server.tool(auth=write)
    def create_bill(record: Bill) -> dict:
        """创建账单；金额和手续费传十进制字符串。"""
        return service.create_bill(record.model_dump())

    @server.tool(auth=write)
    def update_bill(id: str, patch: dict) -> dict:
        """修改账单业务字段；本地及来源身份不可修改。"""
        return service.update_bill(id, patch)

    @server.tool(auth=write)
    def delete_bill(id: str) -> dict:
        """删除账单；来源重新上传可再次创建。"""
        return service.delete_bill(id)

    @server.tool(auth=read)
    def summarize_bills(start_date: str, end_date: str, group_by: str | None = None,
                         type: str | None = None, currency: str | None = None, category: str | None = None,
                         book: str | None = None, account: str | None = None, account_from: str | None = None,
                         account_to: str | None = None, status: str | None = None, query: str | None = None) -> dict:
        """按币种、业务类型汇总金额/手续费；可按 date/month/category/book/account_from/account_to/type/currency 分组。

        默认统计已确认账单，待确认数量单列；指定 status 可统计待确认。不会换汇或合并币种。
        """
        return service.bill_summary(start_date, end_date, group_by, type=type, currency=currency,
            category=category, book=book, account=account, account_from=account_from, account_to=account_to,
            status=status, query=query)

    @server.tool(auth=read)
    def get_collection_status() -> list[dict]:
        """读取两个来源最后成功接收时间；接收新鲜不等于测量日期新鲜。"""
        return service.store.source_status()

    return server
