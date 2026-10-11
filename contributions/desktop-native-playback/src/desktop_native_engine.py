"""Bounded, thread-affine native resources shared by successive media sessions."""
import queue
import threading
import time


class EngineTask:
    def __init__(self, pool, session):
        self.pool, self.session = pool, session
        self.done = threading.Event()
        self.started = False

    def start(self):
        if self.started:
            raise RuntimeError("Native task already started")
        self.pool.submit(self)

    def is_alive(self):
        return self.started and not self.done.is_set()

    def join(self, timeout=None):
        if self.started:
            self.done.wait(timeout)


class EnginePool:
    def __init__(self, cleanup, pump, *, limit=2, idle_seconds=60):
        self.cleanup, self.pump = cleanup, pump
        self.limit, self.idle_seconds = limit, idle_seconds
        self.guard = threading.Lock()
        self.slots = []
        self.closed = False
        self.created = 0
        self.reused = 0

    def task(self, session):
        return EngineTask(self, session)

    def submit(self, task):
        with self.guard:
            if self.closed or task.session.stop.is_set() or task.session.job.cancelled.is_set():
                raise RuntimeError("Native engine is closed or cancelled")
            slot = next((s for s in self.slots if not s['busy']), None)
            if slot is None:
                if len(self.slots) >= self.limit:
                    raise RuntimeError("Native engine limit reached")
                slot = dict(busy=True, task=task, queue=queue.Queue(maxsize=1), resources={})
                slot['thread'] = threading.Thread(target=self._run, args=(slot,),
                    name='desktop-native-engine', daemon=True)
                self.slots.append(slot)
                try:
                    slot['thread'].start()
                except BaseException:
                    self.slots.remove(slot)
                    raise
                self.created += 1
            else:
                slot.update(busy=True, task=task)
                self.reused += 1
            task.started = True
            slot['queue'].put_nowait(task)

    def _run(self, slot):
        idle_at = time.monotonic()
        try:
            while True:
                try:
                    task = slot['queue'].get(timeout=.04)
                except queue.Empty:
                    with self.guard:
                        retire = self.closed or not slot['busy'] and time.monotonic()-idle_at >= self.idle_seconds
                        if retire:
                            # Keep the slot counted until its native resources
                            # have actually been destroyed on this thread.
                            slot['busy'] = True
                    if retire:
                        return
                    self.pump()
                    continue
                if task is None:
                    return
                try:
                    if self.closed:
                        task.session.stop.set()
                    task.session.engine_resources = slot['resources']
                    task.session.run()
                finally:
                    with self.guard:
                        slot.update(busy=False, task=None)
                        idle_at = time.monotonic()
                        task.done.set()
                if self.closed:
                    return
        finally:
            try:
                self.cleanup(slot['resources'])
            finally:
                with self.guard:
                    task = slot.get('task')
                    if task:
                        task.done.set()
                    self.slots.remove(slot)

    def snapshot(self):
        with self.guard:
            return dict(engineSlots=len(self.slots), engineWorkersCreated=self.created,
                        engineAssignmentsReused=self.reused)

    def close(self, timeout=3):
        with self.guard:
            self.closed = True
            slots = list(self.slots)
            for slot in slots:
                if slot['task']:
                    slot['task'].session.stop.set()
                try:
                    slot['queue'].put_nowait(None)
                except queue.Full:
                    pass
        deadline = time.monotonic()+timeout
        for slot in slots:
            if slot['thread'] is not threading.current_thread():
                slot['thread'].join(max(0, deadline-time.monotonic()))
        return all(not s['thread'].is_alive() for s in slots)
