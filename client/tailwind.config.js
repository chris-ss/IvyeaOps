/** @type {import('tailwindcss').Config} */
// 仅作用于 claudecodeui 原生移植子树(src/cloudcli)。
// 关键隔离手段:
//   1. content 只扫 src/cloudcli/** —— 不为 ops 现有页面生成任何 utility
//   2. corePlugins.preflight = false —— 不注入全局 reset(避免污染 ops 16 套主题)
//      cloudcli 自身的 reset 由 index.css 作用域化到 #ccui-root 容器内承担
import typography from '@tailwindcss/typography';

export default {
  darkMode: ['class'],
  content: ['./src/cloudcli/**/*.{js,jsx,ts,tsx}'],
  // 所有 utility 类生成为 `#ccui-root .xxx` —— 自动限定在 cloudcli 容器内,
  // 既不污染 ops,又提权压过 ops 自己的样式。
  important: '#ccui-root',
  corePlugins: {
    preflight: false,
  },
  theme: {
    extend: {
      colors: {
        gray: {
          50:  '#f5f5f5', 100: '#ebebeb', 200: '#d6d6d6', 300: '#b8b8b8',
          400: '#909090', 500: '#6e6e6e', 600: '#505050', 700: '#383838',
          800: '#262626', 900: '#1c1c1c', 950: '#111111',
        },
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: { DEFAULT: 'hsl(var(--primary))', foreground: 'hsl(var(--primary-foreground))' },
        secondary: { DEFAULT: 'hsl(var(--secondary))', foreground: 'hsl(var(--secondary-foreground))' },
        destructive: { DEFAULT: 'hsl(var(--destructive))', foreground: 'hsl(var(--destructive-foreground))' },
        muted: { DEFAULT: 'hsl(var(--muted))', foreground: 'hsl(var(--muted-foreground))' },
        accent: { DEFAULT: 'hsl(var(--accent))', foreground: 'hsl(var(--accent-foreground))' },
        popover: { DEFAULT: 'hsl(var(--popover))', foreground: 'hsl(var(--popover-foreground))' },
        card: { DEFAULT: 'hsl(var(--card))', foreground: 'hsl(var(--card-foreground))' },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      spacing: {
        'safe-area-inset-bottom': 'env(safe-area-inset-bottom)',
        'mobile-nav': 'var(--mobile-nav-total)',
      },
      keyframes: {
        shimmer: {
          '0%': { backgroundPosition: '200% 0' },
          '100%': { backgroundPosition: '-200% 0' },
        },
        'dialog-overlay-show': { from: { opacity: '0' }, to: { opacity: '1' } },
        'dialog-content-show': {
          from: { opacity: '0', transform: 'translate(-50%, -48%) scale(0.96)' },
          to: { opacity: '1', transform: 'translate(-50%, -50%) scale(1)' },
        },
      },
      animation: {
        shimmer: 'shimmer 2s linear infinite',
        'dialog-overlay-show': 'dialog-overlay-show 150ms ease-out',
        'dialog-content-show': 'dialog-content-show 150ms ease-out',
      },
    },
  },
  plugins: [typography],
};
