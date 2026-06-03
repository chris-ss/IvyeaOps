function hexToHsl(hex: string): string {
  const r = parseInt(hex.slice(1, 3), 16) / 255;
  const g = parseInt(hex.slice(3, 5), 16) / 255;
  const b = parseInt(hex.slice(5, 7), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h = 0, s = 0;
  const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: h = ((g - b) / d + (g < b ? 6 : 0)) / 6; break;
      case g: h = ((b - r) / d + 2) / 6; break;
      case b: h = ((r - g) / d + 4) / 6; break;
    }
  }
  return `${Math.round(h * 360)} ${Math.round(s * 100)}% ${Math.round(l * 100)}%`;
}

type ThemeRaw = {
  bg: string; bg1: string; bg2: string; border: string;
  fg: string; fgMuted: string; acc: string; light?: true;
};

// Source colors extracted from IvyeaOps workbench.css (solid equivalents of rgba values)
const RAW: Record<string, ThemeRaw> = {
  dark:             { bg:'#0c0c0c', bg1:'#111111', bg2:'#161616', border:'#262626', fg:'#e8e8e8', fgMuted:'#a8a8a8', acc:'#4ade80' },
  'deep-space':     { bg:'#060c18', bg1:'#0a1020', bg2:'#0e1628', border:'#1e2d4a', fg:'#c8deff', fgMuted:'#84a8cc', acc:'#60a5fa' },
  'smoke-gold':     { bg:'#0c0c0a', bg1:'#111110', bg2:'#181816', border:'#2e2d28', fg:'#e8e0cc', fgMuted:'#aaa090', acc:'#fbbf24' },
  catppuccin:       { bg:'#11111b', bg1:'#1e1e2e', bg2:'#24243a', border:'#383850', fg:'#cdd6f4', fgMuted:'#b8bdd4', acc:'#a78bfa' },
  hermes:           { bg:'#041c1c', bg1:'#0e2322', bg2:'#152b28', border:'#2b3e3a', fg:'#ffe6cb', fgMuted:'#a89e92', acc:'#34d399' },
  light:            { bg:'#f0f0ee', bg1:'#ffffff', bg2:'#f8f8f6', border:'#dededb', fg:'#111111', fgMuted:'#555550', acc:'#16a34a', light: true },
  klein:            { bg:'#000614', bg1:'#000a1e', bg2:'#00102e', border:'#0c1e44', fg:'#c8d8ff', fgMuted:'#7494d4', acc:'#4d7fff' },
  mars:             { bg:'#080a04', bg1:'#0c1006', bg2:'#12180a', border:'#28341a', fg:'#ced8b8', fgMuted:'#96a87c', acc:'#8aad3c' },
  'hermes-orange':  { bg:'#0e0703', bg1:'#160b05', bg2:'#1e1107', border:'#3a1e0c', fg:'#ffe4cc', fgMuted:'#b88c6c', acc:'#f46020' },
  burgundy:         { bg:'#0c0306', bg1:'#14050a', bg2:'#1e0810', border:'#3c1020', fg:'#f2d4dc', fgMuted:'#b87888', acc:'#c03060' },
  mummy:            { bg:'#0e0905', bg1:'#160e08', bg2:'#20150b', border:'#3c2818', fg:'#ead8c0', fgMuted:'#b49c7c', acc:'#c87838' },
  prussian:         { bg:'#00080e', bg1:'#000c16', bg2:'#021222', border:'#0a2030', fg:'#c0d8ee', fgMuted:'#6494b8', acc:'#2d8ab5' },
  tiffany:          { bg:'#040e0c', bg1:'#061412', bg2:'#081c1a', border:'#103028', fg:'#c0eeea', fgMuted:'#5eb4ae', acc:'#50c0b8' },
  titian:           { bg:'#0c0703', bg1:'#140c05', bg2:'#1e1207', border:'#381808', fg:'#f0dcc4', fgMuted:'#b48c6c', acc:'#c86030' },
  schonbrunn:       { bg:'#0c0a03', bg1:'#141104', bg2:'#1e1906', border:'#383010', fg:'#f8f0c0', fgMuted:'#b4ac6c', acc:'#e8b01a' },
  bordeaux:         { bg:'#0a0308', bg1:'#12050e', bg2:'#1a0816', border:'#320e28', fg:'#f0d0e8', fgMuted:'#b478ac', acc:'#b03280' },
};

export function applyIvyeaOpsTheme(themeName: string, target?: HTMLElement): void {
  const c = RAW[themeName] ?? RAW['dark'];
  const root = target ?? document.documentElement;
  const isLight = c.light === true;

  if (isLight) {
    root.classList.remove('dark');
  } else {
    root.classList.add('dark');
  }

  const accHsl = hexToHsl(c.acc);
  const bgHsl  = hexToHsl(c.bg);

  const vars: Record<string, string> = {
    '--background':            hexToHsl(c.bg),
    '--foreground':            hexToHsl(c.fg),
    '--card':                  hexToHsl(c.bg1),
    '--card-foreground':       hexToHsl(c.fg),
    '--popover':               hexToHsl(c.bg1),
    '--popover-foreground':    hexToHsl(c.fg),
    '--primary':               accHsl,
    '--primary-foreground':    isLight ? '0 0% 100%' : bgHsl,
    '--secondary':             hexToHsl(c.bg2),
    '--secondary-foreground':  hexToHsl(c.fg),
    '--muted':                 hexToHsl(c.bg2),
    '--muted-foreground':      hexToHsl(c.fgMuted),
    '--accent':                accHsl,
    '--accent-foreground':     isLight ? '0 0% 100%' : bgHsl,
    '--destructive':           '0 63% 31%',
    '--destructive-foreground': hexToHsl(c.fg),
    '--border':                hexToHsl(c.border),
    '--input':                 hexToHsl(c.border),
    '--ring':                  accHsl,
    '--radius':                '0.5rem',
    '--nav-glass-bg':          `${hexToHsl(c.bg1)} / 0.75`,
    '--nav-tab-glow':          `${accHsl} / 0.20`,
    '--nav-tab-ring':          `${accHsl} / 0.12`,
    '--nav-float-ring':        `${hexToHsl(c.border)} / 0.4`,
    '--nav-divider-color':     `${hexToHsl(c.border)} / 0.6`,
    '--nav-input-bg':          `${hexToHsl(c.bg2)} / 0.6`,
    '--nav-input-focus-ring':  `${accHsl} / 0.22`,
  };

  for (const [k, v] of Object.entries(vars)) {
    root.style.setProperty(k, v);
  }
}
