"""
Test: Send an Adaptive Card to a dynamic recipient via MS Teams chat webhook.

Usage:
    python test_teams_chat_dynamic.py <WEBHOOK_URL> <RECIPIENT_EMAIL>

Example:
    python test_teams_chat_dynamic.py "https://...sig=xxx" "john@company.com"

The payload wraps the card with a "recipient" field:
    {"recipient": "john@company.com", "card": { ...AdaptiveCard... }}

Your Power Automate flow must be configured to parse both fields:
    - Use "recipient" as the dynamic Recipient in the "Post card" action
    - Use "card" as the Adaptive Card body
"""
import sys
import json
import requests
from datetime import datetime


def build_wrapped_payload(recipient_email):
    """Build a payload with recipient + Adaptive Card."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": "[Test] Critical Issue — Demo Project",
                "weight": "Bolder",
                "size": "Medium",
                "wrap": True,
                "color": "Attention",
            },
            {
                "type": "FactSet",
                "facts": [
                    {"title": "Issue",    "value": "Solder paste defect on PCB rev3"},
                    {"title": "Severity", "value": "Critical"},
                    {"title": "Project",  "value": "Demo Project (Acme Corp)"},
                    {"title": "PGM",      "value": "Jane Doe"},
                    {"title": "Stage",    "value": "DVT"},
                    {"title": "Owner",    "value": "John Smith"},
                    {"title": "Due",      "value": "2026-04-15"},
                    {"title": "Time",     "value": now},
                ],
            },
            {
                "type": "TextBlock",
                "text": f"Dynamically routed to **{recipient_email}**",
                "wrap": True,
                "spacing": "Medium",
                "isSubtle": True,
            },
        ],
    }

    return {
        "recipient": recipient_email,
        "card": card,
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: python test_teams_chat_dynamic.py <WEBHOOK_URL> <RECIPIENT_EMAIL>")
        print()
        print("Example:")
        print('  python test_teams_chat_dynamic.py "https://...sig=xxx" "john@company.com"')
        sys.exit(1)

    url = sys.argv[1]
    recipient = sys.argv[2]
    payload = build_wrapped_payload(recipient)

    print(f"Recipient: {recipient}")
    print(f"Webhook:   {url[:80]}...")
    print(f"\nPayload:\n{json.dumps(payload, indent=2)[:600]}...\n")

    resp = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=15,
    )

    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text[:300]}")

    if resp.ok:
        print(f"\n✅ Card sent to {recipient} — check Teams chat!")
    else:
        print("\n❌ Failed. Check Power Automate run history for details.")


if __name__ == "__main__":
    main()
