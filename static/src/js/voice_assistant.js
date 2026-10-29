/** @odoo-module **/
import { Component, useState, useRef, onPatched } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const YES = /^(yes|yeah|yep|confirm|ok|okay|sure|haan|han|ji)\b/;
const NO = /^(no|nope|cancel|stop|nahi|nahin)\b/;

export class VoiceAssistant extends Component {
    static template = "voice_assistant.Systray";

    setup() {
        this.rpc = useService("rpc");
        this.menu = useService("menu");
        this.action = useService("action");
        this.listRef = useRef("messages");
        this.state = useState({
            open: false, listening: false, busy: false,
            transcript: "", typed: "", pending: null,
            messages: [{ role: "bot", text: "Hi! Tap the mic and ask me something." }],
        });
        onPatched(() => {
            if (this.listRef.el) {
                this.listRef.el.scrollTop = this.listRef.el.scrollHeight;
            }
        });

        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        this.supported = !!SR;
        if (SR) {
            this.rec = new SR();
            this.rec.lang = "en-US";
            this.rec.interimResults = true;
            this.rec.continuous = false;
            this.rec.onresult = (ev) => {
                let text = "";
                for (const r of ev.results) {
                    text += r[0].transcript;
                }
                this.state.transcript = text;
                if (ev.results[ev.results.length - 1].isFinal) {
                    this.handle(text);
                }
            };
            this.rec.onend = () => { this.state.listening = false; };
            this.rec.onerror = () => { this.state.listening = false; };
        }
    }

    toggle() { this.state.open = !this.state.open; }

    startListening() {
        if (!this.supported || this.state.listening) { return; }
        window.speechSynthesis && window.speechSynthesis.cancel();
        this.state.transcript = "";
        this.state.listening = true;
        try { this.rec.start(); } catch (e) { this.state.listening = false; }
    }

    onKey(ev) {
        if (ev.key === "Enter" && this.state.typed.trim()) {
            const text = this.state.typed;
            this.state.typed = "";
            this.handle(text);
        }
    }

    say(text) {
        if (window.speechSynthesis) {
            const u = new SpeechSynthesisUtterance(text);
            u.lang = "en-US";
            window.speechSynthesis.speak(u);
        }
    }

    reply(text, extra = {}) {
        this.state.messages.push({ role: "bot", text, ...extra });
        this.say(text);
    }

    // "open sales", "go to purchase" -> switch app using the real menu list
    tryNavigate(text) {
        const m = text.toLowerCase().trim().match(/^(?:open|go to|launch|take me to)\s+(?:the\s+)?(.+?)(?:\s+app)?$/);
        if (!m) { return false; }
        const wanted = m[1].trim();
        const app = this.menu.getApps().find((a) => a.name.toLowerCase().includes(wanted));
        if (!app) { return false; }
        this.menu.selectMenu(app);
        this.reply("Opening " + app.name);
        return true;
    }

    async handle(text) {
        text = (text || "").trim();
        if (!text) { return; }
        this.state.messages.push({ role: "user", text });
        this.state.transcript = "";

        if (this.state.pending) {
            const t = text.toLowerCase();
            if (YES.test(t)) { return this.confirm(true); }
            if (NO.test(t)) { return this.confirm(false); }
        }
        if (this.tryNavigate(text)) { return; }

        this.state.busy = true;
        try {
            const res = await this.rpc("/voice_assistant/process", { text });
            this.afterServer(res);
        } catch (e) {
            this.reply("Something went wrong talking to the server.");
        }
        this.state.busy = false;
    }

    async confirm(yes) {
        const pending = this.state.pending;
        this.state.pending = null;
        if (!yes) { return this.reply("Okay, cancelled."); }
        this.state.busy = true;
        const res = await this.rpc("/voice_assistant/process", { confirmed: true, pending });
        this.state.busy = false;
        this.afterServer(res);
    }

    afterServer(res) {
        this.reply(res.message, { rows: res.rows });
        if (res.confirm) { this.state.pending = res.pending; }
        if (res.open) {
            this.action.doAction({
                type: "ir.actions.act_window",
                res_model: res.open.model,
                res_id: res.open.res_id,
                views: [[false, "form"]],
            });
        }
    }
}

registry.category("systray").add("voice_assistant.mic", { Component: VoiceAssistant }, { sequence: 1 });
