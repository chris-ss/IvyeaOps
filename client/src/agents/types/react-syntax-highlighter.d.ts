declare module 'react-syntax-highlighter';
declare module 'react-syntax-highlighter/dist/esm/styles/prism';
// PrismLight build + per-language deep imports (see lib/prismLight.ts).
declare module 'react-syntax-highlighter/dist/esm/prism-light' {
  import type { ComponentType } from 'react';
  const SyntaxHighlighter: ComponentType<Record<string, unknown>> & {
    registerLanguage: (name: string, language: unknown) => void;
  };
  export default SyntaxHighlighter;
}
declare module 'react-syntax-highlighter/dist/esm/languages/prism/*';
