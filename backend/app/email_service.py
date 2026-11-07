"""Sends incident snapshot emails via Azure Communication Services."""
import base64

from azure.communication.email import EmailClient

from . import settings


def send_incident_email(
    to_address: str, subject: str, body: str, attachment_bytes: bytes, attachment_name: str
) -> None:
    if not settings.AZURE_COMMUNICATION_CONNECTION_STRING or not settings.AZURE_COMMUNICATION_SENDER_EMAIL:
        raise RuntimeError(
            "Azure Communication Services is not configured -- set "
            "AzureCommunicationServiceConnectionString and AzureCommunicationServicesSenderEmail"
        )

    client = EmailClient.from_connection_string(settings.AZURE_COMMUNICATION_CONNECTION_STRING)
    message = {
        "senderAddress": settings.AZURE_COMMUNICATION_SENDER_EMAIL,
        "recipients": {"to": [{"address": to_address}]},
        "content": {
            "subject": subject,
            "plainText": body,
        },
        "attachments": [
            {
                "name": attachment_name,
                "contentType": "image/jpeg",
                "contentInBase64": base64.b64encode(attachment_bytes).decode("ascii"),
            }
        ],
    }
    poller = client.begin_send(message)
    poller.result()
