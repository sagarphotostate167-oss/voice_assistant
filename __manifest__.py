{
    "name": "Voice Assistant",
    "version": "17.0.1.0.0",
    "summary": "Mic icon + voice commands for Accounting, Sales, Purchase and app navigation",
    "category": "Productivity",
    "depends": ["web", "account"],
    "data": [],
    "assets": {
        "web.assets_backend": [
            "voice_assistant/static/src/js/voice_assistant.js",
            "voice_assistant/static/src/xml/voice_assistant.xml",
            "voice_assistant/static/src/scss/voice_assistant.scss",
        ],
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
