# Doover Scheduler

Easily manage schedules within your application using the Doover Scheduler.

This library provides a simple way to check the next scheduled time for a task and receive callbacks when a schedule window is started or ended.

# Installation

The library is published to PyPI, so you can install it using uv or pip:

```bash
uv add doover-scheduler
# or
pip install doover-scheduler
```

You can install the latest development version directly from GitHub:

```bash
uv add git+https://github.com/spaneng/doover-scheduler.git
# or
pip install git+https://github.com/spaneng/doover-scheduler.git
```

# Usage
This first example shows how to use the callbacks to get notified when a schedule starts or ends.

```python
import doover_scheduler

from pydoover.docker import Application

class MyApp(Application):
    async def setup(self):
        self.scheduler = doover_scheduler.ScheduleController(self.device_agent)
        self.scheduler.register(self.on_schedule_start, self.on_schedule_end, self.on_schedule_update)
        await self.scheduler.setup()

        # add a UI component to the application for the scheduler
        self.ui_manager.add_children(doover_scheduler.ScheduleComponent())

    async def main_loop(self):
        await self.scheduler.main_loop()

    @doover_scheduler.on_start
    async def on_schedule_start(self, timeslot):
        print(f"Schedule started: {timeslot}")

    @doover_scheduler.on_end
    async def on_schedule_end(self, timeslot):
        print(f"Schedule finished: {timeslot}")
        
    @doover_scheduler.on_update
    async def on_schedule_update(self, new_schedule):
        print(f"Someone updated the schedule on the website: {new_schedule}")

```

The second example shows how to check the next scheduled time for a task.

```python
import time

import doover_scheduler

from pydoover.docker import Application

class MyApp(Application):
    async def setup(self):
        self.scheduler = doover_scheduler.ScheduleController(self.device_agent)
        self.scheduler.register(self.on_schedule_start, self.on_schedule_end, self.on_schedule_update)
        await self.scheduler.setup()
        
        # add a UI component to the application for the scheduler
        self.ui_manager.add_children(doover_scheduler.ScheduleComponent())

    async def main_loop(self):
        await self.scheduler.main_loop()
        
        current_timeslot = self.scheduler.current_timeslot
        if current_timeslot:
            print(f"The current timeslot will finish in {int(current_timeslot.end_time - time.time())} seconds.")

        next_timeslot = self.scheduler.next_timeslot
        if next_timeslot:
            print(f"The next scheduled timeslot will start in {int(next_timeslot - time.time())} seconds.")
```

## Contributing

For more information, please reach out to the maintainers at hello@doover.com

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.
