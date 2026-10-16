"""Messages to Dai, always through the policy gate."""

from __future__ import annotations

from daikon.mail import Mailbox
from daikon.policy import Channel, OutboundAction, OutboundPolicy


class Notifier:
    def __init__(self, mailbox: Mailbox, policy: OutboundPolicy, dai_email: str) -> None:
        self._mailbox, self._policy, self._dai = mailbox, policy, dai_email

    def send_to_dai(self, subject: str, body: str, kind: str = "digest") -> bool:
        decision = self._policy.evaluate(OutboundAction(Channel.EMAIL, (self._dai,), kind))
        if decision.verdict != "allow":
            return False
        self._mailbox.send([self._dai], subject, body)
        return True
