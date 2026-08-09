'use client';

import React, { useEffect, useRef, useState } from 'react';
import * as THREE from 'three';

interface PipelineCanvasProps {
  activeStep?: number;
  interactive?: boolean;
}

export function PipelineCanvas({ activeStep = 3, interactive = true }: PipelineCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [webglSupported, setWebglSupported] = useState(true);

  useEffect(() => {
    if (!containerRef.current) return;

    const container = containerRef.current;
    let animationFrameId: number;

    try {
      const width = container.clientWidth || window.innerWidth;
      const height = container.clientHeight || 500;

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 1000);
      camera.position.z = 10;

      const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
      renderer.setSize(width, height);
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      container.appendChild(renderer.domElement);

      const group = new THREE.Group();
      scene.add(group);

      // Node Pipeline Titles & Colors
      const steps = [
        { name: 'Ingestion', color: 0x8455ee },
        { name: 'Context Builder', color: 0x6b38d4 },
        { name: 'RCA Agent', color: 0xf5a623 },
        { name: 'Impact Analyzer', color: 0x3b82f6 },
        { name: 'OPA Risk Engine', color: 0xef4444 },
        { name: 'Action Planner', color: 0x10b981 },
        { name: 'Execution Gateway', color: 0x8b5cf6 },
        { name: 'Verification Agent', color: 0x10b981 },
        { name: 'Audit Log Chain', color: 0xa07ede },
      ];

      const nodeCount = steps.length;
      const nodes: THREE.Mesh[] = [];
      const nodeGeo = new THREE.SphereGeometry(0.28, 32, 32);

      // Position nodes in a 3D helix / network cluster
      for (let i = 0; i < nodeCount; i++) {
        const isActive = i <= activeStep;
        const color = isActive ? steps[i].color : 0x4a4551;
        const mat = new THREE.MeshPhongMaterial({
          color: color,
          emissive: isActive ? color : 0x1f1b17,
          emissiveIntensity: isActive ? 0.6 : 0.1,
          shininess: 80,
        });

        const node = new THREE.Mesh(nodeGeo, mat);
        
        // Arrange in a soft curved layout
        const angle = (i / (nodeCount - 1)) * Math.PI * 1.5 - Math.PI * 0.75;
        const x = Math.sin(angle) * 5;
        const y = Math.cos(angle) * 2 - (i - nodeCount / 2) * 0.3;
        const z = (Math.sin(i * 1.2) - 0.5) * 2;

        node.position.set(x, y, z);
        node.userData = {
          originalPos: node.position.clone(),
          index: i,
          pulseOffset: i * 0.5,
          color: color,
        };

        nodes.push(node);
        group.add(node);
      }

      // Create glowing edges between sequential nodes
      const lineGeoPoints: THREE.Vector3[] = [];
      nodes.forEach((node) => lineGeoPoints.push(node.position));
      
      const lineMat = new THREE.LineBasicMaterial({
        color: 0x8455ee,
        transparent: true,
        opacity: 0.4,
      });

      const lineGeo = new THREE.BufferGeometry().setFromPoints(lineGeoPoints);
      const line = new THREE.Line(lineGeo, lineMat);
      group.add(line);

      // Ambient & Point Lighting
      const ambientLight = new THREE.AmbientLight(0xffffff, 0.4);
      scene.add(ambientLight);

      const pointLight1 = new THREE.PointLight(0x8455ee, 2, 50);
      pointLight1.position.set(5, 5, 5);
      scene.add(pointLight1);

      const pointLight2 = new THREE.PointLight(0xf5a623, 1.5, 50);
      pointLight2.position.set(-5, -5, 5);
      scene.add(pointLight2);

      // Mouse Parallax Effect
      let mouseX = 0;
      let mouseY = 0;
      const handleMouseMove = (e: MouseEvent) => {
        if (!interactive) return;
        const rect = container.getBoundingClientRect();
        mouseX = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
        mouseY = -((e.clientY - rect.top) / rect.height - 0.5) * 2;
      };

      if (interactive) {
        window.addEventListener('mousemove', handleMouseMove);
      }

      // Resize Handler
      const handleResize = () => {
        if (!containerRef.current) return;
        const w = containerRef.current.clientWidth || window.innerWidth;
        const h = containerRef.current.clientHeight || 500;
        camera.aspect = w / h;
        camera.updateProjectionMatrix();
        renderer.setSize(w, h);
      };

      window.addEventListener('resize', handleResize);

      // Animation Loop
      let clock = new THREE.Clock();
      const animate = () => {
        animationFrameId = requestAnimationFrame(animate);
        const elapsedTime = clock.getElapsedTime();

        // Rotate scene slightly
        group.rotation.y = Math.sin(elapsedTime * 0.2) * 0.1 + mouseX * 0.3;
        group.rotation.x = Math.cos(elapsedTime * 0.2) * 0.05 + mouseY * 0.2;

        // Pulse nodes
        nodes.forEach((node, i) => {
          const scale = 1 + Math.sin(elapsedTime * 2 + node.userData.pulseOffset) * 0.12;
          node.scale.set(scale, scale, scale);
        });

        renderer.render(scene, camera);
      };

      animate();

      return () => {
        cancelAnimationFrame(animationFrameId);
        window.removeEventListener('resize', handleResize);
        if (interactive) window.removeEventListener('mousemove', handleMouseMove);
        if (container.contains(renderer.domElement)) {
          container.removeChild(renderer.domElement);
        }
        renderer.dispose();
      };
    } catch (err) {
      console.warn('WebGL initialization failed, falling back to 2D visualizer:', err);
      setWebglSupported(false);
    }
  }, [activeStep, interactive]);

  if (!webglSupported) {
    return (
      <div className="w-full h-64 glass-panel rounded-xl flex items-center justify-center p-6 text-center text-gray-400">
        <div>
          <span className="material-symbols-outlined text-4xl text-purple-400 mb-2">hub</span>
          <p className="font-mono text-sm">RISE Multi-Agent Pipeline Visualizer</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative w-full h-[420px] rounded-xl overflow-hidden glass-panel border border-white/10 shadow-2xl">
      <div className="absolute top-4 left-4 z-10 flex items-center space-x-2 bg-black/60 backdrop-blur-md px-3 py-1.5 rounded-full border border-white/10">
        <span className="pulse-dot pulse-dot-green"></span>
        <span className="font-mono text-xs text-gray-300 font-medium tracking-wide uppercase">
          Live 3D Antigravity Pipeline
        </span>
      </div>

      <div ref={containerRef} className="w-full h-full cursor-grab active:cursor-grabbing" />

      {/* Floating Step Legend */}
      <div className="absolute bottom-4 left-4 right-4 z-10 flex flex-wrap items-center justify-between gap-2 bg-black/70 backdrop-blur-md p-3 rounded-lg border border-white/10">
        {[
          'Ingestion',
          'Context',
          'RCA',
          'Impact',
          'Risk/OPA',
          'Planner',
          'Execution',
          'Verify',
        ].map((step, idx) => (
          <div
            key={step}
            className={`flex items-center space-x-1.5 text-xs font-mono px-2.5 py-1 rounded transition-colors ${
              idx <= activeStep
                ? 'bg-purple-900/60 text-purple-200 border border-purple-500/40'
                : 'bg-white/5 text-gray-500 border border-white/5'
            }`}
          >
            <span
              className={`w-2 h-2 rounded-full ${
                idx <= activeStep ? 'bg-amber-400 animate-pulse' : 'bg-gray-600'
              }`}
            />
            <span>{step}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
