import asyncio
import json
import logging
import time
from pathlib import Path

from pydoover.docker import DeviceAgentInterface
from pydoover.docker.device_agent.grpc_stubs import device_agent_pb2
from pydoover.utils import apply_diff

from doover_scheduler import ScheduleController, on_start, on_end, on_update

now = time.time()
data = {
    "schedules": [
        {
            "schedule_name": "Test",
            "frequency": "daily",
            "start_time": now + 5,
            "end_time": now + 100,
            "duration": 1,
            "mode": {"type": ""},
            "edited": 0,
            "timeslots": [
                {
                    "start_time": now + 5,
                    "end_time": now + 10,
                    "duration": 1,
                    "mode": {"type": ""},
                    "edited": 0,
                },
                {
                    "start_time": now + 15,
                    "end_time": now + 20,
                    "duration": 1,
                    "mode": {"type": ""},
                    "edited": 0,
                },
            ],
        }
    ]
}

APP_KEY = "test_app_key"


class MockDeviceAgent(DeviceAgentInterface):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.is_dda_online = True
        self.is_dda_available = True
        self.has_dda_been_online = True

        self.channels = {
            "schedules": data,
        }

    async def wait_for_channels_sync_async(
        self, channel_names: list[str], timeout: int = 5, inter_wait: float = 0.2
    ):
        for channel in channel_names:
            await self.recv_update_callback(
                channel,
                device_agent_pb2.ChannelSubscriptionResponse(
                    channel=device_agent_pb2.ChannelDetails(
                        channel_name=channel,
                        aggregate=json.dumps(self.channels.get(channel, {})),
                    )
                ),
            )
        return True

    async def start_subscription_listener(self, channel_name):
        return

    async def get_channel_aggregate_async(self, channel_name):
        try:
            return self.channels[channel_name]
        except KeyError:
            pass

    async def publish_to_channel_async(
        self,
        channel_name: str,
        message: dict | str,
        record_log: bool = True,
        max_age: int = None,
    ):
        self.channels[channel_name] = apply_diff(
            self.channels.get(channel_name, {}), message
        )


class TestCase:
    def __init__(self):
        self.dda = MockDeviceAgent(APP_KEY)
        self.scheduler = ScheduleController(self.dda)
        self.scheduler.register(self.on_start, self.on_end, self.on_update)

    @on_start
    def on_start(self, *args, **kwargs):
        print(f"start: {args}, {kwargs}")

    @on_end
    def on_end(self, *args, **kwargs):
        print(f"end: {args}, {kwargs}")

    @on_update
    def on_update(self, *args, **kwargs):
        print(f"update: {args}, {kwargs}")


    async def run(self):
        await self.scheduler.setup()
        await asyncio.sleep(1)

        while True:
            print("running")
            await self.scheduler.main_loop()
            await asyncio.sleep(1)


async def main():
    test_case = TestCase()
    await test_case.run()

logging.basicConfig(level=logging.DEBUG)
asyncio.run(main())
