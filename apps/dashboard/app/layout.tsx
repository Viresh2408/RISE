import React from 'react';
import './globals.css';
import { AuthProvider } from '../lib/auth-context';
import { AuthGuard } from '../components/auth-guard';

export const metadata = {
  title: 'RISE — Autonomous Incident Remediation System',
  description: 'Real-time Incident Command Center, Agent Pipeline Diagnostics, and Human Approval Control Plane',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="bg-[#0a0d14] text-gray-100 min-h-screen antialiased">
        <AuthProvider>
          <AuthGuard>{children}</AuthGuard>
        </AuthProvider>
      </body>
    </html>
  );
}
