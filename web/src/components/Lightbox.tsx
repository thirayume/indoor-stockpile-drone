import { useEffect } from "react";

interface Props {
  images: string[]; // filenames, in order
  index: number | null; // open image index; null = closed
  srcFor: (name: string) => string; // full-size URL for a filename
  onIndexChange: (i: number) => void;
  onClose: () => void;
}

const btn: React.CSSProperties = {
  position: "absolute",
  background: "rgba(255,255,255,0.15)",
  color: "#fff",
  border: "none",
  borderRadius: 6,
  fontSize: 28,
  lineHeight: 1,
  padding: "6px 14px",
  cursor: "pointer",
};

/** Full-screen image viewer with keyboard + arrow navigation. */
export default function Lightbox({ images, index, srcFor, onIndexChange, onClose }: Props) {
  useEffect(() => {
    if (index === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight") onIndexChange((index + 1) % images.length);
      else if (e.key === "ArrowLeft") onIndexChange((index - 1 + images.length) % images.length);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, images.length, onIndexChange, onClose]);

  if (index === null) return null;
  const name = images[index];
  const go = (d: number) => onIndexChange((index + d + images.length) % images.length);

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.88)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <button style={{ ...btn, top: 16, right: 20 }} onClick={(e) => { e.stopPropagation(); onClose(); }}>
        ×
      </button>
      <button style={{ ...btn, left: 16 }} onClick={(e) => { e.stopPropagation(); go(-1); }}>
        ‹
      </button>
      <div onClick={(e) => e.stopPropagation()} style={{ textAlign: "center" }}>
        <img
          src={srcFor(name)}
          alt={name}
          style={{ maxWidth: "88vw", maxHeight: "82vh", objectFit: "contain", borderRadius: 4 }}
        />
        <div style={{ color: "#eee", marginTop: 10, fontSize: 13 }}>
          {name} — {index + 1} / {images.length}
        </div>
      </div>
      <button style={{ ...btn, right: 16 }} onClick={(e) => { e.stopPropagation(); go(1); }}>
        ›
      </button>
    </div>
  );
}
