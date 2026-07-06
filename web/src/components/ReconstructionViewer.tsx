import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { PLYLoader } from "three/examples/jsm/loaders/PLYLoader.js";
import { fileUrl } from "../api";

interface Props {
  /** Backend-relative URL of the (downsampled) point cloud, e.g. /volume/files/preview.ply */
  cloudUrl: string;
  /** Backend-relative URL of the stockpile mesh, if one was produced. */
  meshUrl: string | null;
}

const VIEW_HEIGHT = 440;

/** Robust centre/extent from position percentiles: OpenSfM clouds contain
 *  stray far-away points that make the raw bounding box useless for framing. */
function robustFrame(geometry: THREE.BufferGeometry): { center: THREE.Vector3; extent: number } {
  const pos = geometry.getAttribute("position");
  const step = Math.max(1, Math.floor(pos.count / 5000));
  const xs: number[] = [];
  const ys: number[] = [];
  const zs: number[] = [];
  for (let i = 0; i < pos.count; i += step) {
    xs.push(pos.getX(i));
    ys.push(pos.getY(i));
    zs.push(pos.getZ(i));
  }
  const pct = (values: number[], p: number) => {
    const sorted = [...values].sort((a, b) => a - b);
    return sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];
  };
  const lo = new THREE.Vector3(pct(xs, 0.02), pct(ys, 0.02), pct(zs, 0.02));
  const hi = new THREE.Vector3(pct(xs, 0.98), pct(ys, 0.98), pct(zs, 0.98));
  const center = lo.clone().add(hi).multiplyScalar(0.5);
  const extent = Math.max(hi.clone().sub(lo).length(), 1e-3);
  return { center, extent };
}

/** One interactive 3D view showing BOTH result files overlaid:
 *  coloured points = merged.ply (preview), orange mesh = stockpile_mesh.ply. */
export default function ReconstructionViewer({ cloudUrl, meshUrl }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const pointsRef = useRef<THREE.Object3D | null>(null);
  const meshRef = useRef<THREE.Object3D | null>(null);
  const [status, setStatus] = useState("downloading point cloud…");
  const [showPoints, setShowPoints] = useState(true);
  const [showMesh, setShowMesh] = useState(true);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const width = mount.clientWidth || 800;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x1b1e26);
    const camera = new THREE.PerspectiveCamera(60, width / VIEW_HEIGHT, 0.01, 5000);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(width, VIEW_HEIGHT);
    renderer.setPixelRatio(window.devicePixelRatio);
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    scene.add(new THREE.AmbientLight(0xffffff, 0.8));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(1, 2, 1.5);
    scene.add(sun);

    let disposed = false;
    const loader = new PLYLoader();

    loader.load(
      fileUrl(cloudUrl),
      (geometry) => {
        if (disposed) return;
        const { center, extent } = robustFrame(geometry);
        const hasColor = geometry.hasAttribute("color");
        const points = new THREE.Points(
          geometry,
          new THREE.PointsMaterial({
            // Fixed pixel size: always visible regardless of scene scale.
            size: 2.5,
            sizeAttenuation: false,
            vertexColors: hasColor,
            color: hasColor ? 0xffffff : 0x7faaff,
          })
        );
        pointsRef.current = points;
        scene.add(points);

        const axes = new THREE.AxesHelper(extent * 0.3);
        axes.position.copy(center);
        scene.add(axes);

        camera.position
          .copy(center)
          .add(new THREE.Vector3(extent * 0.6, extent * 0.45, extent * 0.6));
        controls.target.copy(center);
        setStatus(`${geometry.getAttribute("position").count.toLocaleString()} points loaded`);
      },
      (event) => {
        if (event.total > 0) {
          setStatus(`downloading point cloud… ${(event.loaded / 1e6).toFixed(1)} MB`);
        }
      },
      () => setStatus("failed to load the point cloud preview")
    );

    if (meshUrl) {
      loader.load(fileUrl(meshUrl), (geometry) => {
        if (disposed) return;
        geometry.computeVertexNormals();
        const mesh = new THREE.Mesh(
          geometry,
          new THREE.MeshStandardMaterial({
            color: 0xff8c3b,
            side: THREE.DoubleSide,
            flatShading: true,
            transparent: true,
            opacity: 0.8,
          })
        );
        meshRef.current = mesh;
        scene.add(mesh);
      });
    }

    let raf = 0;
    const animate = () => {
      raf = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      controls.dispose();
      renderer.dispose();
      mount.removeChild(renderer.domElement);
    };
  }, [cloudUrl, meshUrl]);

  useEffect(() => {
    if (pointsRef.current) pointsRef.current.visible = showPoints;
  }, [showPoints]);
  useEffect(() => {
    if (meshRef.current) meshRef.current.visible = showMesh;
  }, [showMesh]);

  return (
    <div style={{ margin: "12px 0" }}>
      <p style={{ fontSize: 13, color: "#444", marginBottom: 4 }}>
        One view, both result files overlaid — toggle each layer:
      </p>
      <label style={{ fontSize: 13, marginRight: 16 }}>
        <input
          type="checkbox"
          checked={showPoints}
          onChange={(e) => setShowPoints(e.target.checked)}
        />{" "}
        point cloud (<code>merged.ply</code>, coloured dots — the reconstructed scene)
      </label>
      <label style={{ fontSize: 13 }}>
        <input type="checkbox" checked={showMesh} onChange={(e) => setShowMesh(e.target.checked)} />{" "}
        stockpile mesh (<code>stockpile_mesh.ply</code>, orange — the measured volume)
      </label>
      <p style={{ fontSize: 12, color: "#888", margin: "4px 0" }}>{status}</p>
      <div ref={mountRef} style={{ width: "100%", height: VIEW_HEIGHT }} />
      <p style={{ fontSize: 12, color: "#666" }}>
        drag to rotate · scroll to zoom · right-drag to pan
      </p>
    </div>
  );
}
