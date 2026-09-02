import React, { Suspense, useEffect, useMemo, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Grid } from "@react-three/drei";
import * as THREE from "three";

/** Mesh geometry data passed from parent. */
export interface MeshData {
  vertices: number[][];
  faces: number[][];
}

/** Props for ThreeViewer component. */
export interface ThreeViewerProps {
  /** Mesh geometry to display. If null, shows default dipole. */
  meshData?: MeshData | null;
  /** Auto-rotate the camera around the model. */
  autoRotate?: boolean;
  /** Height of the canvas in CSS units. */
  height?: string;
  /** Called when the canvas finishes initializing. */
  onLoad?: () => void;
  /** Fill the height supplied by the parent container. */
  fill?: boolean;
}

function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return reduced;
}

/** Builds a THREE.BufferGeometry from MeshData. */
function buildGeometry(data: MeshData): THREE.BufferGeometry {
  const geo = new THREE.BufferGeometry();
  const vertices: number[] = [];
  const indices: number[] = [];

  for (const v of data.vertices) {
    vertices.push(v[0] ?? 0, v[1] ?? 0, v[2] ?? 0);
  }
  for (const f of data.faces) {
    if (f.length >= 3) {
      indices.push(f[0], f[1], f[2]);
    }
  }

  geo.setAttribute("position", new THREE.Float32BufferAttribute(vertices, 3));
  geo.setIndex(indices);
  geo.computeVertexNormals();

  // Candidate families use very different physical scales. Normalize only the
  // preview mesh; the unmodified SI dimensions remain available in the result.
  geo.computeBoundingBox();
  const bounds = geo.boundingBox;
  if (bounds) {
    const center = bounds.getCenter(new THREE.Vector3());
    const size = bounds.getSize(new THREE.Vector3());
    const largestDimension = Math.max(size.x, size.y, size.z);
    geo.translate(-center.x, -center.y, -center.z);
    if (largestDimension > 0) {
      const previewScale = 0.075 / largestDimension;
      geo.scale(previewScale, previewScale, previewScale);
    }
  }

  geo.computeBoundingSphere();
  return geo;
}

const SceneContent: React.FC<{ meshData?: MeshData | null; autoRotate: boolean }> = ({
  meshData,
  autoRotate,
}) => {
  const reducedMotion = usePrefersReducedMotion();
  const geometry = useMemo(
    () => (meshData ? buildGeometry(meshData) : null),
    [meshData]
  );

  useEffect(() => () => geometry?.dispose(), [geometry]);

  return (
    <>
      <ambientLight intensity={0.35} />
      <directionalLight position={[5, 8, 5]} intensity={0.9} />
      <pointLight position={[0, 0, 0]} intensity={0.7} color="#a9c4e8" distance={0.15} />

      <Grid
        args={[20, 20]}
        position={[0, -0.045, 0]}
        cellSize={0.01}
        cellThickness={0.5}
        cellColor="#26272c"
        sectionSize={0.05}
        sectionThickness={1}
        sectionColor="#34363c"
        fadeDistance={0.8}
        infiniteGrid
      />

      {geometry ? (
        <mesh geometry={geometry}>
          <meshStandardMaterial
            color="#c8cbd2"
            metalness={0.92}
            roughness={0.25}
            side={THREE.DoubleSide}
          />
        </mesh>
      ) : (
        <group>
          <mesh position={[0, 0.0165, 0]}>
            <cylinderGeometry args={[0.0011, 0.0011, 0.03, 24]} />
            <meshStandardMaterial color="#c8cbd2" metalness={0.92} roughness={0.25} />
          </mesh>
          <mesh position={[0, -0.0165, 0]}>
            <cylinderGeometry args={[0.0011, 0.0011, 0.03, 24]} />
            <meshStandardMaterial color="#c8cbd2" metalness={0.92} roughness={0.25} />
          </mesh>
          <mesh>
            <sphereGeometry args={[0.0016, 24, 24]} />
            <meshStandardMaterial
              color="#d6e2f2"
              emissive="#a9c4e8"
              emissiveIntensity={2}
            />
          </mesh>
        </group>
      )}

      <OrbitControls
        autoRotate={autoRotate && !reducedMotion}
        autoRotateSpeed={0.6}
        enableDamping
        dampingFactor={0.1}
      />
    </>
  );
};

/**
 * ThreeViewer — reusable 3D antenna geometry viewer with lighting,
 * ground grid, orbit controls, and a default dipole placeholder.
 */
const ThreeViewer: React.FC<ThreeViewerProps> = ({
  meshData,
  autoRotate = true,
  height = "500px",
  onLoad,
  fill = false,
}) => {
  return (
    <div
      className="well overflow-hidden"
      style={{ width: "100%", height: fill ? "100%" : height, minHeight: fill ? 0 : undefined }}
      role="img"
      aria-label="Interactive 3D antenna geometry"
    >
      <Canvas
        camera={{ position: [0.08, 0.05, 0.1], fov: 42 }}
        style={{ background: "#0c0c0e", width: "100%", height: "100%" }}
        onCreated={() => onLoad?.()}
      >
        <Suspense fallback={null}>
          <SceneContent meshData={meshData} autoRotate={autoRotate} />
        </Suspense>
      </Canvas>
    </div>
  );
};

export default ThreeViewer;
