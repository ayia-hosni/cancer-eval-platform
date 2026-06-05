"""Async Kafka consumer/producer base for all FastAPI ML services."""
import asyncio, json, logging, os
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

log = logging.getLogger(__name__)

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")

async def make_producer() -> AIOKafkaProducer:
    p = AIOKafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_serializer=lambda v: json.dumps(v).encode()
    )
    await p.start()
    return p

async def consume_topic(topic: str, group: str, handler):
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=group,
        value_deserializer=lambda m: json.loads(m.decode()),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )
    await consumer.start()
    log.info(f"Consuming topic={topic} group={group}")
    try:
        async for msg in consumer:
            try:
                await handler(msg.value)
            except Exception as e:
                log.error(f"Handler error on {topic}: {e}", exc_info=True)
    finally:
        await consumer.stop()
