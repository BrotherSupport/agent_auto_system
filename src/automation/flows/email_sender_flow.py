import json

from crewai.flow.flow import Flow, listen, start
from pydantic import BaseModel

from src.automation.progress import append_log
from src.automation.tools.gmail_send_tool import GmailSendTool


class EmailSenderState(BaseModel):
    to: str = ""
    subject: str = ""
    body: str = ""
    cc: str = ""
    run_id: int = 0


class EmailSenderFlow(Flow[EmailSenderState]):

    @start()
    def validate_payload(self):
        missing = [f for f in ("to", "subject", "body") if not getattr(self.state, f, "")]
        if missing:
            raise ValueError(f"Missing required fields: {missing}")
        recipients = [e.strip() for e in self.state.to.split(",") if e.strip()]
        append_log(self.state.run_id, f"Sending to {len(recipients)} recipient(s): {self.state.to}")
        return self.state.model_dump()

    @listen(validate_payload)
    def send_email(self, _):
        append_log(self.state.run_id, f"Connecting to Gmail SMTP...")
        tool = GmailSendTool()
        result = tool._run(
            to=self.state.to,
            subject=self.state.subject,
            body=self.state.body,
            cc=self.state.cc or None,
        )
        if isinstance(result, dict) and result.get("sent"):
            append_log(self.state.run_id, f"Email sent successfully to {self.state.to}")
        else:
            err = result.get("error", "Unknown error") if isinstance(result, dict) else str(result)
            append_log(self.state.run_id, f"Send failed: {err}")
        return json.dumps(result) if isinstance(result, dict) else str(result)
