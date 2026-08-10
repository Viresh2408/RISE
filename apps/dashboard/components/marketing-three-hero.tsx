'use client';

import React, { useEffect, useState, useRef, useMemo } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { Line } from '@react-three/drei';
import * as THREE from 'three';

function NetworkNodes({ mousePos }: { mousePos: { x: number; y: number } }) {
  const groupRef = useRef<THREE.Group>(null);
  const nodeCount = 9;

  const { nodes, edges } = useMemo(() => {
    const nodePositions: THREE.Vector3[] = [];
    for (let i = 0; i < nodeCount; i++) {
      const phi = Math.acos(-1 + (2 * i) / nodeCount);
      const theta = Math.sqrt(nodeCount * Math.PI) * phi;
      const radius = 3.5 + (i % 3) * 0.4;
      nodePositions.push(
        new THREE.Vector3(
          radius * Math.cos(theta) * Math.sin(phi),
          radius * Math.sin(theta) * Math.sin(phi),
          radius * Math.cos(phi)
        )
      );
    }

    const edgePairs: [THREE.Vector3, THREE.Vector3][] = [];
    for (let i = 0; i < nodeCount; i++) {
      for (let j = i + 1; j < nodeCount; j++) {
        if (nodePositions[i].distanceTo(nodePositions[j]) < 4.2) {
          edgePairs.push([nodePositions[i], nodePositions[j]]);
        }
      }
    }

    return { nodes: nodePositions, edges: edgePairs };
  }, []);

  useFrame((state, delta) => {
    if (!groupRef.current) return;
    // Gentle orbit + cursor parallax
    groupRef.current.rotation.y += delta * 0.15;
    groupRef.current.rotation.x += (mousePos.y * 0.2 - groupRef.current.rotation.x) * 0.05;
    groupRef.current.rotation.y += (mousePos.x * 0.3 - groupRef.current.rotation.y) * 0.05;
  });

  return (
    <group ref={groupRef}>
      {/* Network Nodes */}
      {nodes.map((pos, i) => (
        <mesh key={i} position={pos}>
          <sphereGeometry args={[0.22, 24, 24]} />
          <meshStandardMaterial
            color="#8B5CF6"
            emissive="#4C2A85"
            emissiveIntensity={0.8}
            roughness={0.2}
            metalness={0.8}
          />
        </mesh>
      ))}

      {/* Edge Lines via Drei Line component */}
      {edges.map(([p1, p2], i) => (
        <Line
          key={i}
          points={[p1, p2]}
          color="#8B5CF6"
          transparent
          opacity={0.35}
          lineWidth={1.5}
        />
      ))}
    </group>
  );
}

export function MarketingThreeHero() {
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const [mounted, setMounted] = useState(false);
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    setMounted(true);
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    setReducedMotion(mediaQuery.matches);

    const handleMouseMove = (e: MouseEvent) => {
      setMousePos({
        x: (e.clientX / window.innerWidth - 0.5) * 2,
        y: (e.clientY / window.innerHeight - 0.5) * 2,
      });
    };

    window.addEventListener('mousemove', handleMouseMove, { passive: true });
    return () => window.removeEventListener('mousemove', handleMouseMove);
  }, []);

  if (!mounted) {
    return (
      <div className="w-full h-full flex items-center justify-center bg-[#0E0B14] rounded-xl border border-[#E8E2D9]/10">
        <div className="w-40 h-40 rounded-full bg-gradient-to-tr from-[#4C2A85] to-[#8B5CF6] opacity-30 blur-2xl animate-pulse" />
      </div>
    );
  }

  return (
    <div className="w-full h-full relative rounded-xl overflow-hidden bg-[#0E0B14] border border-[#E8E2D9]/10 shadow-2xl">
      <Canvas
        camera={{ position: [0, 0, 9], fov: 60 }}
        dpr={reducedMotion ? 1 : [1, 2]}
        gl={{ alpha: true, antialias: true }}
      >
        <ambientLight intensity={1.2} />
        <pointLight position={[10, 10, 10]} color="#8B5CF6" intensity={2} />
        <pointLight position={[-10, -10, -5]} color="#F5A623" intensity={1} />
        <NetworkNodes mousePos={reducedMotion ? { x: 0, y: 0 } : mousePos} />
      </Canvas>
    </div>
  );
}
