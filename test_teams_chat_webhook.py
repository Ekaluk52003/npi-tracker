"""
Standalone test: Send an Adaptive Card to a MS Teams **chat** webhook.

Usage:
    python test_teams_chat_webhook.py <WEBHOOK_URL>

The webhook URL comes from a Workflows automation created inside a Teams chat
("Post to a chat when a webhook request is received").

The Adaptive Card format is identical for both channel and chat webhooks —
only the URL differs.
"""
import sys
import json
import requests
from datetime import datetime


def build_test_card():
    """Build a sample Adaptive Card that mirrors NPI Tracker alerts."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return {
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
                    {"title": "Impact",   "value": "Line stop risk if not resolved by EOW"},
                    {"title": "Time",     "value": now},
                ],
            },
            {
                "type": "TextBlock",
                "text": "This is a **test card** sent to a Teams chat webhook from NPI Tracker.",
                "wrap": True,
                "spacing": "Medium",
                "isSubtle": True,
            },
        ],
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_teams_chat_webhook.py <WEBHOOK_URL>")
        print("\nTo get the URL:")
        print("  1. Open a Teams chat (1:1 or group)")
        print('  2. Click "+" (Apps) → search "Workflows"')
        print('  3. Choose "Post to a chat when a webhook request is received"')
        print("  4. Copy the generated webhook URL")
        sys.exit(1)

    url = sys.argv[1]
    card = build_test_card()

    print(f"Sending Adaptive Card to:\n  {url[:80]}...")
    print(f"\nPayload:\n{json.dumps(card, indent=2)[:500]}...\n")

    resp = requests.post(
        url,
        json=card,
        headers={"Content-Type": "application/json"},
        timeout=15,
    )

    print(f"Status: {resp.status_code}")
    print(f"Response: {resp.text[:300]}")

    if resp.ok:
        print("\n✅ Card sent successfully — check your Teams chat!")
    else:
        print("\n❌ Failed. Common issues:")
        print("  - URL expired or incorrect")
        print("  - Workflow is turned off in Power Automate")
        print("  - Network/proxy blocking outbound HTTPS")


if __name__ == "__main__":
    main()
