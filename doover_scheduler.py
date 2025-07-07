import asyncio
import itertools
import logging
import time

from pydoover.docker import DeviceAgentInterface
from pydoover.utils import call_maybe_async
from pydoover.ui import RemoteComponent

log = logging.getLogger(__name__)

_UPDATE_CALLBACKS = []
_START_CALLBACKS = []
_END_CALLBACKS = []


# from Sid: todo:
# need to remove expired timeslots
# need to populate channel if its empty


class Schedule:
    # fixme: make these dataclasses

    name: str
    frequency: str
    start_time: float
    end_time: float
    duration: float
    edited: bool
    mode: str
    mode_params: str
    timeslots: list["Timeslot"]

    def __init__(
        self,
        name: str,
        frequency: str,
        start_time: float,
        end_time: float,
        duration: float,
        edited: bool,
        mode: str,
        mode_params: str,
        timeslots: list["Timeslot"],
    ):
        self.name = name
        self.frequency = frequency
        self.start_time = start_time
        self.end_time = end_time
        self.duration = duration
        self.edited = edited
        self.mode = mode
        self.mode_params = mode_params
        self.timeslots = timeslots

        self.timeslots.sort(key=lambda x: x.start_time)

    def __str__(self):
        return f"Schedule(name={self.name}, start_time={self.start_time})"

    def __repr__(self):
        attrs = [
            ("name", self.name),
            ("start_time", self.start_time),
            ("end_time", self.end_time),
            ("duration", self.duration),
            ("mode", self.mode),
        ]
        return f"Schedule<{' '.join([f'{k}={v}' for k, v in attrs])}>"

    def __eq__(self, other):
        if not isinstance(other, Schedule):
            return False
        return (
            self.name == other.name
            and self.start_time == other.start_time
            and self.end_time == other.end_time
            and self.duration == other.duration
            and self.mode == other.mode
        )

    @classmethod
    def from_data(cls, data):
        return cls(
            data["schedule_name"],
            data["frequency"],
            data["start_time"],
            data["end_time"],
            data["duration"],
            data["edited"],
            data["mode"]["type"],
            data["mode"],
            [Timeslot.from_data(ts) for ts in data["timeslots"]],
        )


class Timeslot:
    def __init__(
        self,
        start_time: float,
        end_time: float,
        duration: float,
        edited: bool,
        mode: str,
        mode_params: str,
    ):
        self.start_time = start_time
        self.end_time = end_time
        self.duration = duration
        self.edited = edited
        self.mode = mode
        self.mode_params = mode_params

    def __str__(self):
        return f"Timeslot(start_time={self.start_time}, end_time={self.end_time})"

    def __repr__(self):
        attrs = [
            ("start_time", self.start_time),
            ("end_time", self.end_time),
            ("duration", self.duration),
            ("mode", self.mode),
        ]
        return f"Timeslot<{' '.join([f'{k}={v}' for k, v in attrs])}>"

    @classmethod
    def from_data(cls, data):
        return cls(
            data["start_time"],
            data["end_time"],
            data["duration"],
            data["edited"],
            data["mode"]["type"],
            data["mode"],
        )


class ScheduleController:
    SCHEDULE_CHANNEL = "schedules"

    def __init__(self, dda: DeviceAgentInterface):
        self.dda = dda

        log.info(f"dda_iface status: {self.dda.get_is_dda_online()}")

        self._latest_schedule_data = None

        self._next_slot_start_time = None
        self._next_slot_end_time = None

        self.schedules: list[Schedule] = []
        self.sorted_slots: list[Timeslot] = []

        self._update_callbacks = []
        self._on_start_callbacks = []
        self._on_end_callbacks = []

        self._start_schedule_task = None
        self._end_schedule_task = None

    async def _run_check_start_schedules(self):
        while True:
            try:
                next_slot = self.next_timeslot
                if next_slot is None:
                    log.info("No next timeslot available, exiting to wait for schedule update")
                    return

                await asyncio.sleep(next_slot.start_time - time.time())
                log.info(f"New timeslot started: {next_slot}!")
                if next_slot != self.current_timeslot:
                    # uh oh, something went wrong.
                    continue

                for cb in self._on_start_callbacks:
                    try:
                        await call_maybe_async(cb, next_slot)
                    except Exception as e:
                        log.error(f"Error in on_start callback: {e}")
            except asyncio.CancelledError:
                log.info("Schedule check loop cancelled")
                break
            except Exception as e:
                log.error(f"Error in schedule check loop: {e}")
                await asyncio.sleep(1)

    async def _run_check_end_schedules(self):
        while True:
            try:
                print(self.schedules)
                slot = self.current_timeslot

                if slot is None:
                    slot = self.next_timeslot

                if slot is None:
                    log.info("No current timeslot available, exiting to wait for schedule update")
                    return

                await asyncio.sleep(slot.end_time - time.time())
                for cb in self._on_end_callbacks:
                    try:
                        await call_maybe_async(cb, slot)
                    except Exception as e:
                        log.error(f"Error in on_end callback: {e}")
            except asyncio.CancelledError:
                log.info("Schedule check loop cancelled")
                break
            except Exception as e:
                log.error(f"Error in schedule check loop: {e}")
                await asyncio.sleep(1)

    async def setup(self):
        log.info("starting schedule channel subscriptions")
        self.dda.add_subscription(self.SCHEDULE_CHANNEL, self._on_schedule_update)
        self._run_tasks()

    def _run_tasks(self):
        if self._start_schedule_task is not None:
            self._start_schedule_task.cancel()
        if self._end_schedule_task is not None:
            self._end_schedule_task.cancel()

        self._start_schedule_task = asyncio.create_task(self._run_check_start_schedules())
        self._end_schedule_task = asyncio.create_task(self._run_check_end_schedules())


    async def main_loop(self):
        if len(self.sorted_slots) == 0:
            log.debug("No timeslots available, waiting for schedule update")
            return

        next_slot = self.sorted_slots[0]
        if next_slot.end_time < time.time():
            log.info("Next slot has expired, clearing expired timeslots")
            await self.clear_expired_timeslots()

    def register(self, *callbacks):
        """Register callbacks to be called when the schedule is updated, starts, or ends.

        These callbacks must be registered with a decorator - either `@on_update`, `@on_start`, or `@on_end`.
        """
        for cb in callbacks:
            if getattr(cb, "_scheduler_on_update", False):
                self.add_update_callback(cb)
            if getattr(cb, "_scheduler_on_start", False):
                self.add_on_start_callback(cb)
            if getattr(cb, "_scheduler_on_end", False):
                self.add_on_end_callback(cb)

    def add_update_callback(self, callback):
        """Register a callback to be called when the schedule is updated."""
        self._update_callbacks.append(callback)

    def add_on_start_callback(self, callback):
        """Register a callback to be called when a timeslot starts."""
        self._on_start_callbacks.append(callback)

    def add_on_end_callback(self, callback):
        """Register a callback to be called when a timeslot ends."""
        self._on_end_callbacks.append(callback)

    async def _on_schedule_update(self, _, data):
        log.info(f"schedule update received: {data}")
        if data is None:
            return

        self.schedules = [Schedule.from_data(s) for s in data.get("schedules", [])]
        slots = itertools.chain.from_iterable(s.timeslots for s in self.schedules)
        self.sorted_slots: list[Timeslot] = list(
            sorted(slots, key=lambda x: x.start_time)
        )
        self._run_tasks()

        for cb in self._update_callbacks:
            await call_maybe_async(cb)

    @property
    def current_timeslot(self) -> Timeslot | None:
        """Returns the current timeslot if it is active, otherwise None.

        If the next timeslot is in the future, it will also return None.
        """
        if not self.sorted_slots:
            return None

        # fixme: check if it's in the past...

        first = self.sorted_slots[0]
        if first.start_time > time.time():
            # it's in the future, so no current timeslot
            return None

        return first

    @property
    def next_timeslot(self) -> Timeslot | None:
        """Returns the next timeslot that is in the future.

        This will **not** return the current timeslot if it is active.
        """
        # Iterate through until we get one that is in the future.
        # It should only be 1-2 elements.
        for slot in self.sorted_slots:
            if slot.start_time > time.time():
                return slot
        return None

    async def clear_all_schedule_events(self):
        await self.dda.publish_to_channel_async(
            self.SCHEDULE_CHANNEL, {"schedules": []}
        )

    async def clear_expired_timeslots(self):
        current = await self.dda.get_channel_aggregate_async(self.SCHEDULE_CHANNEL)
        for s in current["schedules"]:
            s["timeslots"] = [n for n in s["timeslots"] if n["end_time"] >= time.time()]

        schedules = [s for s in current["schedules"] if len(s["timeslots"]) > 0]
        await self.dda.publish_to_channel_async(
            self.SCHEDULE_CHANNEL, {"schedules": schedules}
        )


def on_start(func):
    """Callback to be called when a schedule starts."""
    func._scheduler_on_start = True
    return func

def on_end(func):
    """Callback to be called when a schedule ends."""
    func._scheduler_on_end = True
    return func

def on_update(func):
    """Callback to be called when the schedule is updated."""
    func._scheduler_on_update = True
    return func


class ScheduleComponent(RemoteComponent):
    def __init__(self):
        super().__init__(
            name="schedule_component",
            display_name="Schedule Component",
            component_url="https://spaneng.github.io/doover_scheduler/SchedulerComponent.js",
        )
