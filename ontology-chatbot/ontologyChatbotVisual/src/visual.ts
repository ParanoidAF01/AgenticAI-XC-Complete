"use strict";
import "../style/visual.less";
import powerbi from "powerbi-visuals-api";
import VisualConstructorOptions = powerbi.extensibility.visual.VisualConstructorOptions;
import VisualUpdateOptions = powerbi.extensibility.visual.VisualUpdateOptions;
import IVisual = powerbi.extensibility.visual.IVisual;

interface ChatSession {
    id: string;
    title: string;
    profile: string;
    created_at: string;
    messages: ChatMessage[];
}

interface ChatMessage {
    id: string;
    role: "user" | "assistant";
    content: string;
    timestamp: string;
    sql?: string[];
    chart_config?: any;
    has_error?: boolean;
}

interface ProfileInfo {
    name: string;
    display_name: string;
}

export class Visual implements IVisual {
    private target: HTMLElement;
    private container: HTMLElement;
    
    // Sidebar
    private sidebar: HTMLElement;
    private sessionList: HTMLElement;
    private profileSelect: HTMLSelectElement;
    
    // Main Area
    private mainArea: HTMLElement;
    private header: HTMLElement;
    private messagesArea: HTMLElement;
    private inputSection: HTMLElement;
    
    // Input
    private textarea: HTMLTextAreaElement;
    private sendBtn: HTMLButtonElement;
    
    // Typing indicator
    private typingIndicator: HTMLElement;
    
    // Sidebar overlay
    private overlay: HTMLElement;
    
    // State
    private sessions: ChatSession[] = [];
    private currentSession: ChatSession | null = null;
    private profiles: ProfileInfo[] = [];
    private isSidebarOpen: boolean = true;
    private isLoading: boolean = false;
    
    // Settings
    private apiBaseUrl: string = "https://ppfhvdck-8000.asse.devtunnels.ms";
    private apiKey: string = "";

    constructor(options: VisualConstructorOptions) {
        this.target = options.element;
        
        // Build the DOM
        this.container = document.createElement("div");
        this.container.className = "chatbot-root";
        this.target.appendChild(this.container);
        
        // Sidebar overlay (dims background when sidebar is open)
        this.overlay = document.createElement("div");
        this.overlay.className = "sidebar-overlay sidebar-overlay--visible";
        this.overlay.onclick = () => this.toggleSidebar();
        this.container.appendChild(this.overlay);
        
        this.buildSidebar();
        this.buildMainArea();
        
        // Load initial data
        this.fetchProfiles();
    }

    public update(options: VisualUpdateOptions) {
        // Read settings from dataView
        if (options.dataViews && options.dataViews[0] && options.dataViews[0].metadata && options.dataViews[0].metadata.objects) {
            const objects: any = options.dataViews[0].metadata.objects;
            if (objects.chatbotSettings) {
                if (objects.chatbotSettings.apiBaseUrl !== undefined) {
                    this.apiBaseUrl = objects.chatbotSettings.apiBaseUrl;
                }
                if (objects.chatbotSettings.apiKey !== undefined) {
                    this.apiKey = objects.chatbotSettings.apiKey;
                }
            }
        }
    }

    private buildSidebar() {
        this.sidebar = document.createElement("div");
        this.sidebar.className = "chat-sidebar chat-sidebar--open";
        
        // Top section
        const topSection = document.createElement("div");
        topSection.className = "sidebar-top";
        
        const newChatBtn = document.createElement("button");
        newChatBtn.className = "new-chat-btn";
        newChatBtn.appendChild(this.createSvgIcon("M12 4v16m-8-8h16", "0 0 24 24", "icon-plus"));
        newChatBtn.appendChild(document.createTextNode(" New Chat"));
        newChatBtn.onclick = () => this.startNewSession();
        topSection.appendChild(newChatBtn);
        
        // Sessions section
        const sessionsSection = document.createElement("div");
        sessionsSection.className = "sidebar-sessions";
        
        const sessionsLabel = document.createElement("div");
        sessionsLabel.className = "sidebar-section-label";
        sessionsLabel.innerText = "RECENT CHATS";
        sessionsSection.appendChild(sessionsLabel);
        
        this.sessionList = document.createElement("ul");
        this.sessionList.className = "session-list";
        sessionsSection.appendChild(this.sessionList);
        
        // Bottom section
        const bottomSection = document.createElement("div");
        bottomSection.className = "sidebar-bottom";
        
        const profileLabel = document.createElement("label");
        profileLabel.innerText = "Database Profile";
        bottomSection.appendChild(profileLabel);
        
        this.profileSelect = document.createElement("select");
        this.profileSelect.className = "profile-select";
        this.profileSelect.onchange = () => this.startNewSession();
        bottomSection.appendChild(this.profileSelect);
        
        this.sidebar.appendChild(topSection);
        this.sidebar.appendChild(sessionsSection);
        this.sidebar.appendChild(bottomSection);
        
        this.container.appendChild(this.sidebar);
    }

    private buildMainArea() {
        this.mainArea = document.createElement("div");
        this.mainArea.className = "chat-main chat-main--shifted";
        // Main area gets margin if sidebar is open, assuming handled in CSS via flex or margin
        
        // Header
        this.header = document.createElement("div");
        this.header.className = "chat-header";
        
        const toggleBtn = document.createElement("button");
        toggleBtn.className = "sidebar-toggle";
        toggleBtn.appendChild(this.createSvgIcon("M3 6h18M3 12h12M3 18h18", "0 0 24 24"));
        toggleBtn.onclick = () => this.toggleSidebar();
        
        const title = document.createElement("div");
        title.className = "chat-header-title";
        title.innerText = "Ontology Assistant";
        
        const clearBtn = document.createElement("button");
        clearBtn.className = "clear-btn";
        clearBtn.appendChild(this.createSvgIcon("M3 6h18M8 6V4h8v2M5 6v14a1 1 0 001 1h12a1 1 0 001-1V6", "0 0 24 24"));
        clearBtn.onclick = () => {
            if (confirm("Are you sure you want to clear this chat?")) {
                if (this.currentSession) {
                    this.currentSession.messages = [];
                    this.renderMessages();
                }
            }
        };
        
        this.header.appendChild(toggleBtn);
        this.header.appendChild(title);
        this.header.appendChild(clearBtn);
        
        // Messages Area
        this.messagesArea = document.createElement("div");
        this.messagesArea.className = "chat-messages";
        
        // Typing indicator
        this.typingIndicator = document.createElement("div");
        this.typingIndicator.className = "typing-indicator";
        this.typingIndicator.style.display = "none";
        
        const dotsWrapper = document.createElement("div");
        dotsWrapper.className = "typing-dots";
        for (let i = 0; i < 3; i++) {
            const dot = document.createElement("div");
            dot.className = "typing-dot";
            dotsWrapper.appendChild(dot);
        }
        this.typingIndicator.appendChild(dotsWrapper);
        const typingText = document.createElement("div");
        typingText.className = "typing-text";
        typingText.innerText = "Analyzing your data...";
        this.typingIndicator.appendChild(typingText);
        
        // Input Section
        this.inputSection = document.createElement("div");
        this.inputSection.className = "chat-input-section";
        
        const composerInner = document.createElement("div");
        composerInner.className = "composer-inner";
        
        this.textarea = document.createElement("textarea");
        this.textarea.className = "composer-input";
        this.textarea.placeholder = "Ask a question about your data...";
        this.textarea.rows = 1;
        this.textarea.addEventListener("input", () => {
            this.textarea.style.height = "auto";
            this.textarea.style.height = Math.min(this.textarea.scrollHeight, 200) + "px";
        });
        this.textarea.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                this.handleSend();
            }
        });
        
        this.sendBtn = document.createElement("button");
        this.sendBtn.className = "composer-send";
        this.sendBtn.appendChild(this.createSvgIcon("M3.5 10L16.5 3.5L10 16.5L8.5 11.5L3.5 10Z", "0 0 20 20", "icon-send", "currentColor", true));
        this.sendBtn.onclick = () => this.handleSend();
        
        composerInner.appendChild(this.textarea);
        composerInner.appendChild(this.sendBtn);
        
        const hint = document.createElement("div");
        hint.className = "composer-hint";
        hint.innerText = "Enter to send • Shift+Enter for new line";
        
        this.inputSection.appendChild(composerInner);
        this.inputSection.appendChild(hint);
        
        this.mainArea.appendChild(this.header);
        this.mainArea.appendChild(this.messagesArea);
        this.mainArea.appendChild(this.inputSection);
        
        this.container.appendChild(this.mainArea);
        
        this.renderMessages();
    }

    private toggleSidebar() {
        this.isSidebarOpen = !this.isSidebarOpen;
        if (this.isSidebarOpen) {
            this.sidebar.classList.add("chat-sidebar--open");
            this.overlay.classList.add("sidebar-overlay--visible");
            this.mainArea.classList.add("chat-main--shifted");
        } else {
            this.sidebar.classList.remove("chat-sidebar--open");
            this.overlay.classList.remove("sidebar-overlay--visible");
            this.mainArea.classList.remove("chat-main--shifted");
        }
    }

    private startNewSession() {
        const profile = this.profileSelect.value || "";
        this.currentSession = {
            id: this.generateUUID(),
            title: "New Chat",
            profile: profile,
            created_at: new Date().toISOString(),
            messages: []
        };
        
        // If not already in list (it will be added when first message is sent)
        this.renderMessages();
        this.updateSessionList();
    }

    private async fetchProfiles() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/v1/powerbi/profiles`, {
                method: "GET",
                headers: {
                    "X-API-Key": this.apiKey
                }
            });
            
            if (response.ok) {
                this.profiles = await response.json();
                this.profileSelect.innerHTML = "";
                this.profiles.forEach(p => {
                    const opt = document.createElement("option");
                    opt.value = p.name;
                    opt.text = p.display_name;
                    this.profileSelect.appendChild(opt);
                });
                if (!this.currentSession && this.profiles.length > 0) {
                    this.startNewSession();
                }
            }
        } catch (e) {
            console.error("Failed to fetch profiles", e);
        }
    }

    private async handleSend() {
        if (this.isLoading) return;
        
        const text = this.textarea.value.trim();
        if (!text) return;
        
        if (!this.currentSession) {
            this.startNewSession();
        }
        
        // Add session to list if it's the first message
        if (this.currentSession.messages.length === 0) {
            this.currentSession.title = this.truncate(text, 40);
            this.sessions.unshift(this.currentSession);
            this.updateSessionList();
        }
        
        const userMsg: ChatMessage = {
            id: this.generateUUID(),
            role: "user",
            content: text,
            timestamp: new Date().toISOString()
        };
        
        this.currentSession.messages.push(userMsg);
        
        this.textarea.value = "";
        this.textarea.style.height = "auto";
        this.renderMessages();
        this.scrollToBottom();
        
        this.setLoading(true);
        
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/v1/powerbi/chat`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-API-Key": this.apiKey
                },
                body: JSON.stringify({
                    message: text,
                    session_id: this.currentSession.id,
                    profile: this.currentSession.profile
                })
            });
            
            const data = await response.json();
            
            const assistantMsg: ChatMessage = {
                id: this.generateUUID(),
                role: "assistant",
                content: data.answer || "Error processing request.",
                timestamp: new Date().toISOString(),
                sql: data.sql,
                chart_config: data.chart_config,
                has_error: data.has_error
            };
            
            this.currentSession.messages.push(assistantMsg);
        } catch (e) {
            const errorMsg: ChatMessage = {
                id: this.generateUUID(),
                role: "assistant",
                content: "Network error. Please try again.",
                timestamp: new Date().toISOString(),
                has_error: true
            };
            this.currentSession.messages.push(errorMsg);
        } finally {
            this.setLoading(false);
            this.renderMessages();
            this.scrollToBottom();
        }
    }

    private setLoading(loading: boolean) {
        this.isLoading = loading;
        if (loading) {
            this.sendBtn.innerHTML = "";
            this.sendBtn.appendChild(this.createSvgIcon("M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83", "0 0 24 24", "icon-spin"));
            this.sendBtn.style.opacity = "0.4";
            this.textarea.disabled = true;
            this.messagesArea.appendChild(this.typingIndicator);
            this.typingIndicator.style.display = "flex";
        } else {
            this.sendBtn.innerHTML = "";
            this.sendBtn.appendChild(this.createSvgIcon("M3.5 10L16.5 3.5L10 16.5L8.5 11.5L3.5 10Z", "0 0 20 20", "icon-send", "currentColor", true));
            this.sendBtn.style.opacity = "1";
            this.textarea.disabled = false;
            this.textarea.focus();
            this.typingIndicator.style.display = "none";
        }
    }

    private updateSessionList() {
        this.sessionList.innerHTML = "";
        
        this.sessions.forEach(session => {
            const li = document.createElement("li");
            li.className = "session-item";
            if (this.currentSession && this.currentSession.id === session.id) {
                li.classList.add("session-item--active");
            }
            
            li.onclick = () => {
                this.currentSession = session;
                this.profileSelect.value = session.profile;
                this.updateSessionList();
                this.renderMessages();
            };
            
            const icon = this.createSvgIcon("M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z", "0 0 24 24", "", "currentColor", false, "1.5");
            li.appendChild(icon);
            
            const contentDiv = document.createElement("div");
            contentDiv.style.flex = "1";
            contentDiv.style.minWidth = "0";
            
            const title = document.createElement("div");
            title.className = "session-title";
            title.innerText = session.title;
            contentDiv.appendChild(title);
            
            const date = document.createElement("div");
            date.className = "session-date";
            date.innerText = this.formatRelativeDate(session.created_at);
            contentDiv.appendChild(date);
            
            li.appendChild(contentDiv);
            
            const delBtn = document.createElement("button");
            delBtn.className = "session-delete-btn";
            delBtn.appendChild(this.createSvgIcon("M3 6h18M8 6V4h8v2M5 6v14a1 1 0 001 1h12a1 1 0 001-1V6", "0 0 24 24", "", "currentColor", false, "1.5"));
            delBtn.onclick = (e) => {
                e.stopPropagation();
                if (confirm("Delete this chat?")) {
                    this.sessions = this.sessions.filter(s => s.id !== session.id);
                    if (this.currentSession && this.currentSession.id === session.id) {
                        this.currentSession = null;
                        this.startNewSession();
                    } else {
                        this.updateSessionList();
                    }
                }
            };
            li.appendChild(delBtn);
            
            this.sessionList.appendChild(li);
        });
    }

    private renderMessages() {
        this.messagesArea.innerHTML = "";
        
        if (!this.currentSession || this.currentSession.messages.length === 0) {
            this.renderWelcomeScreen();
            return;
        }
        
        this.currentSession.messages.forEach(msg => {
            const msgEl = document.createElement("div");
            msgEl.className = `message message--${msg.role}`;
            if (msg.has_error) {
                msgEl.classList.add("message--error");
            }
            
            const avatar = document.createElement("div");
            avatar.className = "message-avatar";
            const avatarInner = document.createElement("div");
            avatarInner.className = msg.role === "user" ? "avatar avatar--user" : "avatar avatar--assistant";
            avatarInner.textContent = msg.role === "user" ? "U" : "A";
            avatar.appendChild(avatarInner);
            
            const body = document.createElement("div");
            body.className = "message-body";
            
            const content = document.createElement("div");
            content.className = "message-content";
            
            if (msg.role === "user") {
                content.innerText = msg.content;
            } else {
                content.innerHTML = this.renderMarkdown(this.escapeHtml(msg.content));
                
                if (msg.sql && msg.sql.length > 0) {
                    const sqlContainer = document.createElement("div");
                    
                    const toggleSqlBtn = document.createElement("button");
                    toggleSqlBtn.className = "view-sql-btn";
                    toggleSqlBtn.innerText = "View SQL";
                    
                    const codeBlock = document.createElement("div");
                    codeBlock.className = "sql-code-block";
                    codeBlock.style.display = "none";
                    
                    const pre = document.createElement("pre");
                    const code = document.createElement("code");
                    code.innerText = msg.sql.join("\n\n");
                    pre.appendChild(code);
                    codeBlock.appendChild(pre);
                    
                    toggleSqlBtn.onclick = () => {
                        if (codeBlock.style.display === "none") {
                            codeBlock.style.display = "block";
                            toggleSqlBtn.innerText = "Hide SQL";
                        } else {
                            codeBlock.style.display = "none";
                            toggleSqlBtn.innerText = "View SQL";
                        }
                    };
                    
                    sqlContainer.appendChild(toggleSqlBtn);
                    sqlContainer.appendChild(codeBlock);
                    content.appendChild(sqlContainer);
                }
            }
            
            const time = document.createElement("div");
            time.className = "message-time";
            time.innerText = this.formatTime(new Date(msg.timestamp));
            
            body.appendChild(content);
            body.appendChild(time);
            
            msgEl.appendChild(avatar);
            msgEl.appendChild(body);
            
            this.messagesArea.appendChild(msgEl);
        });
        
        if (this.isLoading) {
            this.messagesArea.appendChild(this.typingIndicator);
        }
    }

    private renderWelcomeScreen() {
        const welcome = document.createElement("div");
        welcome.className = "welcome-screen";
        
        const icon = document.createElement("div");
        icon.className = "welcome-icon";
        icon.appendChild(this.createSvgIcon("M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z", "0 0 24 24", "", "currentColor", false, "1.5"));
        welcome.appendChild(icon);
        
        const title = document.createElement("h1");
        title.innerText = "Ontology Assistant";
        welcome.appendChild(title);
        
        const subtitle = document.createElement("p");
        subtitle.innerText = "Ask questions about your insurance data";
        welcome.appendChild(subtitle);
        
        const grid = document.createElement("div");
        grid.className = "suggestion-grid";
        
        const suggestions = [
            "How many active policies are there?",
            "Total premium by line of business",
            "Top 5 states by policy count",
            "Show premium trend by quarter"
        ];
        
        suggestions.forEach(text => {
            const card = document.createElement("div");
            card.className = "suggestion-card";
            card.innerText = text;
            card.onclick = () => {
                this.textarea.value = text;
                this.handleSend();
            };
            grid.appendChild(card);
        });
        
        welcome.appendChild(grid);
        this.messagesArea.appendChild(welcome);
    }

    private scrollToBottom() {
        this.messagesArea.scrollTop = this.messagesArea.scrollHeight;
    }

    // Helpers
    private createSvgIcon(pathD: string, viewBox: string, className: string = "", strokeOrFill: string = "currentColor", useFill: boolean = false, strokeWidth: string = "2"): SVGSVGElement {
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("viewBox", viewBox);
        svg.setAttribute("width", "100%");
        svg.setAttribute("height", "100%");
        if (className) svg.setAttribute("class", className);
        
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", pathD);
        
        if (className === "icon-spin") {
            // override for spinner
            const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
            circle.setAttribute("cx", "12");
            circle.setAttribute("cy", "12");
            circle.setAttribute("r", "10");
            circle.setAttribute("stroke", "currentColor");
            circle.setAttribute("stroke-width", "2");
            circle.setAttribute("fill", "none");
            circle.setAttribute("stroke-dasharray", "30 70");
            svg.appendChild(circle);
            return svg;
        }
        
        if (useFill) {
            path.setAttribute("fill", strokeOrFill);
        } else {
            path.setAttribute("stroke", strokeOrFill);
            path.setAttribute("stroke-width", strokeWidth);
            path.setAttribute("stroke-linecap", "round");
            if (viewBox === "0 0 24 24" && strokeWidth === "2") {
                path.setAttribute("stroke-linejoin", "round");
            }
            path.setAttribute("fill", "none");
        }
        
        svg.appendChild(path);
        return svg;
    }

    private generateUUID(): string {
        if (window.crypto && window.crypto.randomUUID) {
            return window.crypto.randomUUID();
        }
        return Date.now().toString(36) + Math.random().toString(36).substring(2);
    }

    private formatTime(date: Date): string {
        let hours = date.getHours();
        let minutes: any = date.getMinutes();
        const ampm = hours >= 12 ? 'PM' : 'AM';
        hours = hours % 12;
        hours = hours ? hours : 12; // the hour '0' should be '12'
        minutes = minutes < 10 ? '0' + minutes : minutes;
        return hours + ':' + minutes + ' ' + ampm;
    }

    private formatRelativeDate(dateStr: string): string {
        const date = new Date(dateStr);
        const now = new Date();
        const diffMs = now.getTime() - date.getTime();
        const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));
        
        if (diffDays === 0 && now.getDate() === date.getDate()) {
            return "Today";
        } else if (diffDays === 1 || (diffDays === 0 && now.getDate() !== date.getDate())) {
            return "Yesterday";
        } else {
            return date.toLocaleDateString();
        }
    }

    private truncate(str: string, maxLen: number): string {
        if (str.length <= maxLen) return str;
        return str.substring(0, maxLen - 3) + "...";
    }

    private escapeHtml(text: string): string {
        const div = document.createElement("div");
        div.innerText = text;
        return div.innerHTML;
    }

    private renderMarkdown(text: string): string {
        let html = text;
        
        // Code blocks: ```code```
        html = html.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>');
        
        // Inline code: `code`
        html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
        
        // Bold: **text**
        html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        
        // Italic: *text*
        html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>');
        
        // Lists: - item
        // A simple approach for unordered lists
        html = html.replace(/(?:^|\n)- (.+)/g, '<ul><li>$1</li></ul>');
        html = html.replace(/<\/ul>\n<ul>/g, '\n'); // merge adjacent
        
        // Numbered lists: 1. item
        html = html.replace(/(?:^|\n)\d+\. (.+)/g, '<ol><li>$1</li></ol>');
        html = html.replace(/<\/ol>\n<ol>/g, '\n'); // merge adjacent
        
        // Tables: simple parsing
        if (html.includes('|')) {
            const tableRegex = /((?:\|.+\|\n?)+)/g;
            html = html.replace(tableRegex, (match) => {
                const rows = match.trim().split('\n');
                let tableHtml = '<table>';
                rows.forEach((row, index) => {
                    if (row.includes('---')) return; // skip separator
                    const cells = row.split('|').filter(c => c.trim() !== '');
                    tableHtml += '<tr>';
                    cells.forEach(cell => {
                        if (index === 0) {
                            tableHtml += `<th>${cell.trim()}</th>`;
                        } else {
                            tableHtml += `<td>${cell.trim()}</td>`;
                        }
                    });
                    tableHtml += '</tr>';
                });
                tableHtml += '</table>';
                return tableHtml;
            });
        }
        
        // Newlines
        html = html.replace(/\n/g, '<br>');
        
        // Cleanup leftover <br> inside pre
        html = html.replace(/<pre><code>([\s\S]*?)<\/code><\/pre>/g, (match, p1) => {
            return `<pre><code>${p1.replace(/<br>/g, '\n')}</code></pre>`;
        });
        
        return html;
    }
}
