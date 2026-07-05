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

/** Interactive 3D view of the reconstruction: coloured points + volume mesh. */
export default function ReconstructionViewer({ cloudUrl, meshUrl }: Props) {
  const mountRef = useRef<HTMLDivElement>(null);
  const meshRef = useRef<THREE.Object3D | null>(null);
  const [status, setStatus] = useState("loading point cloud…");
  const [showMesh, setShowMesh] = useState(true);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return;

    const width = mount.clientWidth || 800;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x14161c);
    const camera = new THREE.PerspectiveCamera(60, width / VIEW_HEIGHT, 0.01, 1000);
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
        geometry.computeBoundingBox();
        const box = geometry.boundingBox!;
        const center = box.getCenter(new THREE.Vector3());
        const extent = box.getSize(new THREE.Vector3()).length();
        const hasColor = geometry.hasAttribute("color");
        const points = new THREE.Points(
          geometry,
          new THREE.PointsMaterial({
            size: extent / 350,
            vertexColors: hasColor,
            color: hasColor ? 0xffffff : 0x7faaff,
          })
        );
        scene.add(points);
        camera.position.copy(center).add(new THREE.Vector3(extent * 0.5, extent * 0.4, extent * 0.5));
        controls.target.copy(center);
        setStatus("");
      },
      undefined,
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
    if (meshRef.current) meshRef.current.visible = showMesh;
  }, [showMesh]);

  return (
    <div style={{ margin: "12px 0" }}>
      <label style={{ fontSize: 13 }}>
        <input type="checkbox" checked={showMesh} onChange={(e) => setShowMesh(e.target.checked)} />{" "}
        show measured stockpile mesh (orange = the volume you get)
      </label>
      {status && <p>{status}</p>}
      <div ref={mountRef} style={{ width: "100%", height: VIEW_HEIGHT }} />
      <p style={{ fontSize: 12, color: "#666" }}>
        drag to rotate · scroll to zoom · right-drag to pan
      </p>
    </div>
  );
}
