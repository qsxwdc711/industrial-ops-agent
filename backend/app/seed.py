import math
import random
from datetime import timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, insert, select

from .knowledge import chunk_text
from .schemas import Telemetry
from .storage import Storage, utcnow

MANUALS = [
    ('水泵轴承温升与振动排查指南', 'manual',
     '本文件为项目演示知识，不代表设备厂商标准。\n\n轴承温度和振动同步上升时，应优先检查润滑不足、轴承磨损、轴系对中偏差和基础松动。仅凭温度或振动数值不能确认具体根因。\n\n核查轴承测点趋势、润滑记录、振动频谱和现场异响；结合电流判断负载变化。若存在持续异常，按现场规程安排人工复核。\n\n示例阈值：温度 70°C 提醒、85°C 严重；振动速度 4.5mm/s 提醒、7.1mm/s 严重。阈值应由实际设备规格配置。'),
    ('离心泵汽蚀故障案例', 'case',
     '本案例为演示资料。\n\n离心泵汽蚀可能伴随不稳定振动、噪声增加和出口压力波动。吸入口堵塞、液位不足或吸入条件变化都可能造成此类现象。\n\n检查吸入口过滤器、液位、阀门开度与压力趋势；对比轴承温升，避免把所有振动异常都归因于汽蚀。'),
    ('电机过热与电流异常检查流程', 'procedure',
     '本流程为项目演示资料。\n\n电机温度上升可能与过载、散热通道堵塞、轴承润滑不足或供电不平衡相关。电流趋势有助于区分负载变化与机械异常。\n\n结合电流、温度、振动、环境温度以及维护记录检查。现场测量与处理由人员依据作业规程执行，系统仅提供辅助建议。'),
    ('旋转设备日常巡检记录规范', 'procedure',
     '巡检记录应包含设备编号、测点、采集时间、温度、振动、电流、压力、环境温度和现场观察。\n\n异常趋势分析必须对齐时间窗口，区分采样缺失和真实变化，并保留原始日志与告警编号作为证据。\n\n故障报告应分别记录已观察到的事实、待验证的原因假设和下一步人工检查事项。'),
]


def seed(storage: Storage):
    with storage.engine.connect() as conn:
        if conn.scalar(select(func.count()).select_from(storage.devices)):
            return
    rng = random.Random(20261011)
    now = utcnow()
    devices = []
    for i in range(12):
        pump = i < 8
        number = i + 101 if pump else i - 8 + 201
        devices.append(dict(id=f'{"P" if pump else "M"}-{number}',
            name=f'{"循环水泵" if pump else "驱动电机"} {i + 1:02d}', kind='pump' if pump else 'motor',
            area=['循环水站', '冷却系统', '动力车间'][i % 3], status='normal', demo=1))
    with storage.engine.begin() as conn:
        conn.execute(insert(storage.devices), devices)
    items = []
    for i, device in enumerate(devices):
        for step in range(96):
            progress = max(0, (step - 76) / 19)
            temperature = 47 + i * 1.2 + math.sin(step / 8) * 3 + rng.random() * 2
            vibration = 1.4 + rng.random() * 0.9
            if i == 0:
                temperature += progress * 42
                vibration += progress * 6.5
            elif i in (5, 10):
                temperature += progress * 20
                vibration += progress * 3
            items.append(Telemetry(event_id=f'seed-{device["id"]}-{step}', device_id=device['id'],
                timestamp=(now - timedelta(minutes=(95 - step) * 15)).replace(tzinfo=timezone.utc),
                temperature=round(temperature, 1), vibration=round(vibration, 2),
                current=round(15 + i * 1.3 + rng.random() * 3, 1),
                pressure=round(0.48 + rng.random() * 0.12, 3) if i < 8 else 0,
                ambient_temperature=26.4, humidity=58, source='demo-simulator'))
        with storage.engine.begin() as conn:
            messages = ['设备网关连接正常，采集间隔 15 分钟', '完成例行巡检，待核对润滑记录']
            if i == 0:
                messages += ['轴承测点温度连续上升', '振动测点超过演示阈值，建议复核现场状态']
            conn.execute(insert(storage.logs), [dict(id=str(uuid4()), device_id=device['id'],
                level='warning' if i == 0 and j >= 2 else 'info', message='[演示] ' + text,
                created_at=now - timedelta(minutes=(len(messages) - j) * 20)) for j, text in enumerate(messages)])
    storage.store_batch(items)
    for title, category, content in MANUALS:
        document_id = str(uuid4())
        storage.save_document(document_id, title, category, content, chunk_text(content))
        storage.set_index_status(document_id, 'local')
    storage.aggregate()
