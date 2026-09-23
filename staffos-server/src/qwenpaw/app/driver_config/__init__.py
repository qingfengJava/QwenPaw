# -*- coding: utf-8 -*-
"""Driver configuration storage plane (PG authoritative + file projection).

T12：数字员工外部能力（MCP/ACP）驱动卡与凭据的存储平面。文件
（``drivers/{protocol}/{name}.yaml`` + ``credentials.yaml``）为运行时投影，
PG（``driver_cards`` / ``driver_credentials``）为持久权威源，二者由
:class:`~qwenpaw.app.driver_config_service.DriverConfigService` 写穿保持一致。

@author qingfeng
"""
