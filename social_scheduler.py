"""Single-worker idle tick; never builds prompts or talks to OneBot."""
import time


class SocialScheduler:
    def __init__(self, engine, role_for, callback, clock=time.monotonic):
        self.engine, self.role_for, self.callback = engine, role_for, callback
        self.clock, self.next_check = clock, 0

    def tick(self):
        now = self.clock()
        if now < self.next_check:
            return
        self.next_check = now + 30
        for scope in self.engine.scopes():
            candidate = self.engine.choose(scope, self.role_for(scope))
            if candidate is not None:
                self.callback(candidate)
                break  # one attempt per idle tick; passive jobs get priority
