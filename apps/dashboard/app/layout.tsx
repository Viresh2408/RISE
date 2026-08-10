import React from 'react';
import { Fraunces, Inter } from 'next/font/google';
import './globals.css';
import { AuthProvider } from '../lib/auth-context';
import { AuthGuard } from '../components/auth-guard';

const fraunces = Fraunces({
  subsets: ['latin'],
  variable: '--font-display',
  weight: ['400', '600', '700'],
  style: ['normal', 'italic'],
  display: 'swap',
});

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-body',
  weight: ['400', '500', '600'],
  display: 'swap',
});

export const metadata = {
  title: 'RISE — Autonomous Incident Remediation System',
  description: 'Real-time Incident Command Center, Agent Pipeline Diagnostics, and Human Approval Control Plane',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`dark scroll-smooth ${fraunces.variable} ${inter.variable}`}>
      <body className="min-h-screen antialiased bg-[#0E0B14] text-[#FAF7F2] font-body">
        <AuthProvider>
          <AuthGuard>{children}</AuthGuard>
        </AuthProvider>
      </body>
    </html>
  );
}
