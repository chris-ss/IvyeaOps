/**
 * Shared syntax highlighter — PrismLight with only the languages we actually
 * meet in chat / code views, instead of the full `Prism` build (which bundles
 * EVERY Prism language and was the single biggest contributor to the 2.6MB
 * Agents chunk). Unregistered languages render as plain text (no crash).
 */
import SyntaxHighlighter from 'react-syntax-highlighter/dist/esm/prism-light';

import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash';
import c from 'react-syntax-highlighter/dist/esm/languages/prism/c';
import cpp from 'react-syntax-highlighter/dist/esm/languages/prism/cpp';
import csharp from 'react-syntax-highlighter/dist/esm/languages/prism/csharp';
import css from 'react-syntax-highlighter/dist/esm/languages/prism/css';
import diff from 'react-syntax-highlighter/dist/esm/languages/prism/diff';
import docker from 'react-syntax-highlighter/dist/esm/languages/prism/docker';
import go from 'react-syntax-highlighter/dist/esm/languages/prism/go';
import java from 'react-syntax-highlighter/dist/esm/languages/prism/java';
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript';
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json';
import jsx from 'react-syntax-highlighter/dist/esm/languages/prism/jsx';
import markdown from 'react-syntax-highlighter/dist/esm/languages/prism/markdown';
import markup from 'react-syntax-highlighter/dist/esm/languages/prism/markup';
import powershell from 'react-syntax-highlighter/dist/esm/languages/prism/powershell';
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python';
import rust from 'react-syntax-highlighter/dist/esm/languages/prism/rust';
import scss from 'react-syntax-highlighter/dist/esm/languages/prism/scss';
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql';
import tsx from 'react-syntax-highlighter/dist/esm/languages/prism/tsx';
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript';
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml';

const langs: Array<[string[], unknown]> = [
  [['bash', 'sh', 'shell', 'zsh'], bash],
  [['c'], c],
  [['cpp', 'c++'], cpp],
  [['csharp', 'cs'], csharp],
  [['css'], css],
  [['diff', 'patch'], diff],
  [['docker', 'dockerfile'], docker],
  [['go', 'golang'], go],
  [['java'], java],
  [['javascript', 'js'], javascript],
  [['json', 'jsonc'], json],
  [['jsx'], jsx],
  [['markdown', 'md'], markdown],
  [['markup', 'html', 'xml', 'svg'], markup],
  [['powershell', 'ps1'], powershell],
  [['python', 'py'], python],
  [['rust', 'rs'], rust],
  [['scss', 'sass'], scss],
  [['sql'], sql],
  [['tsx'], tsx],
  [['typescript', 'ts'], typescript],
  [['yaml', 'yml'], yaml],
];

for (const [names, lang] of langs) {
  for (const name of names) {
    SyntaxHighlighter.registerLanguage(name, lang);
  }
}

export default SyntaxHighlighter;
