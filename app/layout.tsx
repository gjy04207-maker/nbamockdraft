import './globals.css';
import type { ReactNode } from 'react';

export const metadata = {
  title: '2026 Mock Draft Command Center',
  description: 'NBA 模拟选秀、签约权与交易价值评估工具台',
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh">
      <body>{children}</body>
    </html>
  );
}
