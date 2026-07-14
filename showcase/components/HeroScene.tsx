"use client";

import { useMemo, useRef, useState, useEffect } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Float, Line } from "@react-three/drei";
import * as THREE from "three";

type NodeSpec = {
  pos: [number, number, number];
  color: string;
  scale: number;
  engine?: boolean;
};

/** Deterministic PRNG so edge layout is stable across renders */
function mulberry32(seed: number) {
  return () => {
    let t = (seed += 0x6d2b79f5);
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function GraphNodes({ nodes }: { nodes: NodeSpec[] }) {
  const group = useRef<THREE.Group>(null);
  useFrame((state) => {
    if (!group.current) return;
    const t = state.clock.elapsedTime;
    group.current.rotation.y = t * 0.08;
    group.current.rotation.x = Math.sin(t * 0.12) * 0.08;
    const { x, y } = state.pointer;
    group.current.position.x = THREE.MathUtils.lerp(
      group.current.position.x,
      x * 0.4,
      0.04,
    );
    group.current.position.y = THREE.MathUtils.lerp(
      group.current.position.y,
      y * 0.3,
      0.04,
    );
  });

  const edges = useMemo(() => {
    const rand = mulberry32(42);
    const lines: [THREE.Vector3, THREE.Vector3][] = [];
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        if (rand() > 0.55) continue;
        lines.push([
          new THREE.Vector3(...nodes[i].pos),
          new THREE.Vector3(...nodes[j].pos),
        ]);
      }
    }
    const engines = nodes.filter((n) => n.engine);
    const workers = nodes.filter((n) => !n.engine);
    for (const e of engines) {
      for (const w of workers.slice(0, 4)) {
        lines.push([
          new THREE.Vector3(...e.pos),
          new THREE.Vector3(...w.pos),
        ]);
      }
    }
    return lines;
  }, [nodes]);

  return (
    <group ref={group}>
      {edges.map((pts, i) => (
        <Line
          key={i}
          points={pts}
          color="#2de2e6"
          lineWidth={1}
          transparent
          opacity={0.35}
        />
      ))}
      {nodes.map((n, i) => (
        <Float
          key={i}
          speed={1.2 + (i % 3) * 0.2}
          floatIntensity={0.4}
          rotationIntensity={0.2}
        >
          <mesh position={n.pos} scale={n.scale}>
            <icosahedronGeometry args={[0.35, n.engine ? 1 : 0]} />
            <meshStandardMaterial
              color={n.color}
              emissive={n.color}
              emissiveIntensity={n.engine ? 0.9 : 0.45}
              roughness={0.35}
              metalness={0.4}
            />
          </mesh>
        </Float>
      ))}
      <mesh>
        <sphereGeometry args={[0.15, 16, 16]} />
        <meshBasicMaterial color="#ff2a6d" transparent opacity={0.85} />
      </mesh>
    </group>
  );
}

function makeNodes(): NodeSpec[] {
  const nodes: NodeSpec[] = [
    { pos: [0, 0.2, 0], color: "#ff2a6d", scale: 1.15, engine: true },
    { pos: [-0.6, 0.5, 0.3], color: "#c8f542", scale: 0.85, engine: true },
    { pos: [0.55, -0.35, 0.25], color: "#c8f542", scale: 0.75, engine: true },
  ];
  const ring = 8;
  for (let i = 0; i < ring; i++) {
    const a = (i / ring) * Math.PI * 2;
    nodes.push({
      pos: [Math.cos(a) * 2.2, Math.sin(a * 1.3) * 0.7, Math.sin(a) * 2.0],
      color: "#2de2e6",
      scale: 0.55 + (i % 3) * 0.08,
    });
  }
  return nodes;
}

export default function HeroScene() {
  const nodes = useMemo(() => makeNodes(), []);
  const [ok, setOk] = useState(true);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) setOk(false);
  }, []);

  if (!ok) {
    return (
      <div
        className="absolute inset-0 -z-10 bg-[radial-gradient(ellipse_at_center,#0c1a1c_0%,#05060a_70%)]"
        aria-hidden
      />
    );
  }

  return (
    <div className="motion-safe-only absolute inset-0 -z-10" aria-hidden>
      <Canvas
        dpr={[1, 1.75]}
        camera={{ position: [0, 0.4, 5.5], fov: 48 }}
        gl={{ antialias: true, alpha: true, powerPreference: "high-performance" }}
        style={{ background: "transparent" }}
        onCreated={({ gl }) => {
          gl.setClearColor(new THREE.Color("#05060a"), 0);
        }}
      >
        <ambientLight intensity={0.35} />
        <pointLight position={[4, 4, 4]} intensity={1.2} color="#2de2e6" />
        <pointLight position={[-3, -2, 2]} intensity={0.7} color="#ff2a6d" />
        <GraphNodes nodes={nodes} />
        <fog attach="fog" args={["#05060a", 4, 12]} />
      </Canvas>
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(ellipse at center, transparent 20%, #05060a 75%)",
        }}
      />
    </div>
  );
}
