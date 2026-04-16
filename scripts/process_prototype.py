"""
Post-processes Stitch-generated HTML files to fix alignment and navigation.
"""
import re
import os

PROTO_DIR = os.path.join(os.path.dirname(__file__), "..", "prototype")

# Page config: filename → (page title, active nav item text)
PAGES = {
    "dashboard.html": ("Dashboard", "Dashboard"),
    "pipelines.html": ("Pipelines", "Pipelines"),
    "pipeline_detail.html": ("Pipeline Detail", "Pipelines"),
    "chatbot.html": ("AI Assistant", "Chatbot"),
    "settings.html": ("Listener Control", "Settings"),
    "reports.html": ("Reports & Analytics", "Reports"),
}

# Standard navigation items (order matters)
NAV_ITEMS = [
    ("Dashboard", "dashboard", "dashboard.html"),
    ("Pipelines", "account_tree", "pipelines.html"),
    ("Chatbot", "chat_bubble", "chatbot.html"),
    ("Reports", "analytics", "reports.html"),
    ("Settings", "settings", "settings.html"),
]

INJECT_JS = """
<script>
// Collapse sidebar
function toggleSidebar() {
    const sidebar = document.getElementById('main-sidebar');
    const mainContent = document.getElementById('main-content');
    if (!sidebar) return;
    const labels = sidebar.querySelectorAll('.nav-label');
    const logo = sidebar.querySelectorAll('.logo-text');
    const btn = sidebar.querySelector('.collapse-toggle');
    const refreshBtn = sidebar.querySelector('.refresh-btn-container');
    
    sidebar.classList.toggle('sidebar-collapsed');
    const collapsed = sidebar.classList.contains('sidebar-collapsed');
    
    if (collapsed) {
        sidebar.style.width = '72px';
        sidebar.classList.remove('w-[240px]');
        labels.forEach(l => l.style.display = 'none');
        logo.forEach(l => l.style.display = 'none');
        if (refreshBtn) refreshBtn.style.display = 'none';
        if (btn) btn.querySelector('span').textContent = 'chevron_right';
        if (mainContent) {
            mainContent.classList.remove('ml-[240px]');
            mainContent.classList.add('ml-[72px]');
        }
    } else {
        sidebar.style.width = '240px';
        sidebar.classList.add('w-[240px]');
        labels.forEach(l => l.style.display = '');
        logo.forEach(l => l.style.display = '');
        if (refreshBtn) refreshBtn.style.display = '';
        if (btn) btn.querySelector('span').textContent = 'chevron_left';
        if (mainContent) {
            mainContent.classList.remove('ml-[72px]');
            mainContent.classList.add('ml-[240px]');
        }
    }
}

// Theme toggle
function toggleTheme() {
    const html = document.documentElement;
    const icon = document.getElementById('themeToggleIcon');
    if (html.classList.contains('dark')) {
        html.classList.remove('dark');
        html.classList.add('light');
        if (icon) icon.textContent = 'dark_mode';
    } else {
        html.classList.remove('light');
        html.classList.add('dark');
        if (icon) icon.textContent = 'light_mode';
    }
}
</script>
"""

INJECT_CSS = """
<style>
#main-sidebar { transition: width 0.25s ease, padding 0.25s ease; overflow-x: hidden; }
#main-content { transition: margin-left 0.25s ease; }
.collapse-toggle { 
    background: none; border: none; cursor: pointer; 
    color: #807660; padding: 4px; border-radius: 6px;
    transition: background 0.2s;
    flex-shrink: 0;
}
.collapse-toggle:hover { background: #e2e2e2; }
.dark .collapse-toggle:hover { background: #334155; }
.collapse-toggle span { font-size: 18px; }
.nav-item { white-space: nowrap; }
</style>
"""

def build_sidebar_html(active_item: str) -> str:
    items_html = ""
    for label, icon, href in NAV_ITEMS:
        # Avoid linking to self with full reload if it's active. Wait, doing window.location is fine.
        # It's cleaner to just have href.
        if label == active_item:
            items_html += f'''
<a class="nav-item flex items-center gap-3 text-[#1a1c1c] dark:text-white font-bold border-l-4 border-[#f5c518] pl-4 py-3 hover:bg-[#e2e2e2] dark:hover:bg-slate-800 transition-colors active:scale-95 bg-[#e2e2e2]/50 dark:bg-slate-800/50" href="{href}">
<span class="material-symbols-outlined shrink-0" data-icon="{icon}">{icon}</span>
<span class="text-sm nav-label">{label}</span>
</a>'''
        else:
            items_html += f'''
<a class="nav-item flex items-center gap-3 text-[#4e4633] dark:text-slate-400 pl-5 py-3 hover:bg-[#e2e2e2] dark:hover:bg-slate-800 transition-colors active:scale-95 border-l-4 border-transparent" href="{href}">
<span class="material-symbols-outlined shrink-0" data-icon="{icon}">{icon}</span>
<span class="text-sm nav-label">{label}</span>
</a>'''

    # Changed from sticky to fixed for bulletproof alignment
    return f'''<aside id="main-sidebar" class="w-[240px] h-screen fixed left-0 top-0 bg-[#f3f3f3] dark:bg-slate-900 flex flex-col py-8 px-4 flex-shrink-0 z-50 shadow-[2px_0_12px_rgba(0,0,0,0.05)] border-r border-[#e2e2e2] dark:border-slate-800">
<div class="mb-12 px-2 flex items-center justify-between">
<div class="overflow-hidden">
<h1 class="text-xl font-bold tracking-tighter text-[#1a1c1c] dark:text-white logo-text whitespace-nowrap">ADF Healer</h1>
<p class="text-[10px] uppercase tracking-widest text-[#745b00] dark:text-[#f5c518] font-bold mt-1 logo-text whitespace-nowrap">Self-Healing Engine</p>
</div>
<button class="collapse-toggle ml-2" onclick="toggleSidebar()" title="Collapse sidebar">
<span class="material-symbols-outlined">chevron_left</span>
</button>
</div>
<nav class="flex-1 space-y-2 overflow-y-auto no-scrollbar">
{items_html}
</nav>
<div class="mt-auto px-2 pt-6 refresh-btn-container">
<button class="w-full py-3 bg-[#f5c518] text-[#1a1c1c] font-bold rounded-xl text-xs flex items-center justify-center gap-2 shadow-sm hover:opacity-90 transition-opacity active:scale-95">
<span class="material-symbols-outlined text-sm" data-icon="refresh">refresh</span>
<span class="nav-label">Refresh</span>
</button>
</div>
</aside>'''


def process_file(filename: str, page_title: str, active_item: str):
    filepath = os.path.join(PROTO_DIR, filename)
    if not os.path.exists(filepath):
        print(f"  [SKIP] {filename} not found")
        return
    
    with open(filepath, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Replace sidebar
    new_sidebar = build_sidebar_html(active_item)
    sidebar_pattern = re.compile(r'<(aside|nav)[^>]*class="[^"]*(h-screen|h-full)[^"]*"[^>]*>.*?</\1>', re.DOTALL | re.IGNORECASE)
    
    if sidebar_pattern.search(html):
        html = sidebar_pattern.sub(new_sidebar, html, count=1)

    # 2. Add ID to <main> and set margin-left
    # First, strip out old flex styles from body because we use fixed layout now
    html = re.sub(r'<body([^>]*)style="display: flex;[^"]*"', r'<body\1', html)
    html = html.replace('flex min-h-screen', 'min-h-screen')

    # Now fix <main> tag to have id="main-content" and ml-[240px]
    main_pattern = re.compile(r'<main([^>]*)>')
    
    def repl_main(match):
        attrs = match.group(1)
        # Remove old ml- mappings
        attrs = re.sub(r'\bml-\w+\b', '', attrs)
        attrs = re.sub(r'\bml-\[[^\]]+\]\b', '', attrs)
        
        # Add id and our margin class
        if 'id="' not in attrs:
            attrs += ' id="main-content"'
        else:
            attrs = re.sub(r'id="[^"]*"', 'id="main-content"', attrs)
            
        if 'class="' in attrs:
            attrs = re.sub(r'class="([^"]*)"', r'class="\1 ml-[240px] transition-all"', attrs)
        else:
            attrs += ' class="ml-[240px] transition-all"'
            
        return f'<main{attrs}>'

    if '<main' in html:
        html = main_pattern.sub(repl_main, html)
    else:
        # Wrap the remaining content in <main> if none exists (everything after aside)
        parts = html.split('</aside>')
        if len(parts) == 2:
            content = parts[1]
            body_end = content.find('</body>')
            if body_end != -1:
                new_content = '\n<main id="main-content" class="ml-[240px] transition-all min-w-0 overflow-x-hidden min-h-screen flex flex-col">\n' + content[:body_end] + '\n</main>\n' + content[body_end:]
                html = parts[0] + '</aside>' + new_content

    # 3. Add link to Pipeline Details specifically in pipelines.html
    if filename == "pipelines.html":
        # Find rows looking like pipelines and make them clickable
        # Looking for things like <tr> or <div> rows that have PL_
        # A simple robust way: replace PL_ pipeline text with a click wrapper, or just replace the <tr> definition
        # Since it's Stitch generated it's likely a <tr> containing PL_
        
        # We can find table rows and add cursor-pointer and onclick
        tr_pattern = re.compile(r'(<tr[^>]*hover:bg-[^>]*>)')
        html = tr_pattern.sub(r'\1 ', html) # Just add space
        
        # A more hacky but reliable way for Stitch prototypes:
        html = re.sub(r'<tr([^>]*)>', '<tr\\1 style="cursor: pointer;" onclick="window.location.href=\'pipeline_detail.html\'">', html)
        # Fix double onclick if it happens
        html = html.replace('onclick="window.location.href=\'pipeline_detail.html\'" style="cursor: pointer;" onclick="window.location.href=\'pipeline_detail.html\'"', 'onclick="window.location.href=\'pipeline_detail.html\'" style="cursor: pointer;"')
    
    # 3b. Make dashboard recent activity rows click to pipeline detail
    if filename == "dashboard.html":
        # "group cursor-pointer" are the rows
        html = re.sub(
            r'(<div[^>]*class="[^"]*group cursor-pointer[^"]*"[^>]*)>', 
            '\\1 onclick="window.location.href=\'pipeline_detail.html\'">', 
            html)
            
    # 3c. Fix back button on pipeline detail
    if filename == "pipeline_detail.html":
        html = re.sub(
            r'href="javascript:void\(0\)"(>\s*<span[^>]+data-icon="arrow_back")',
            r'onclick="window.history.back()" style="cursor:pointer"\1',
            html
        )

    # 4. Inject CSS before </head>
    if '<style>\n#main-sidebar' not in html:
        html = html.replace('</head>', INJECT_CSS + '</head>')
    
    # 5. Inject JS before </body>
    if 'function toggleSidebar()' not in html:
        html = html.replace('</body>', INJECT_JS + '</body>')
    
    # Verify relative link cleanup
    dummy_link = re.compile(r'<a([^>]+)href="#"')
    html = dummy_link.sub(r'<a\1href="javascript:void(0)"', html)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"  [OK] {filename} processed")

def main():
    print("=" * 50)
    print("Fixing alignment and navigation")
    print("=" * 50)
    for filename, (title, active) in PAGES.items():
        process_file(filename, title, active)

if __name__ == "__main__":
    main()
