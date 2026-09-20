import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { VenueFormCard } from "./VenueFormCard";
import type { FormDraft } from "./formTypes";

interface VenueItem {
  name: string;
  location: string;
  capacity: number;
  type: string;
  auto_approve?: boolean;
  approval?: string;
}

/** 对话内只读场地目录卡片：列出全部场地，点「预约此场地」直接转预约表单并预选。 */
export function VenueCatalogCard({
  user,
  messageId,
}: {
  user: { user_id: string };
  messageId?: string;
}) {
  const [venues, setVenues] = useState<Record<string, VenueItem>>({});
  const [picked, setPicked] = useState<string>("");
  useEffect(() => {
    api.listVenues().then((r) => setVenues(r.venues || {})).catch(() => {});
  }, []);
  if (picked) {
    return (
      <VenueFormCard
        draft={{ process_type: "venue_reservation", fields: { venue_id: picked } } as FormDraft}
        user={user}
        messageId={messageId}
        onBack={() => setPicked("")}
      />
    );
  }
  const typeIcon: Record<string, string> = {
    classroom: "🏫",
    activity_room: "🎯",
    lecture_hall: "🎤",
    computer_lab: "💻",
  };
  return (
    <div className="form-card">
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 10 }}>
        🏫 可预约场地（{Object.keys(venues).length} 个）
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
        {Object.keys(venues).length === 0 && (
          <div style={{ fontSize: 12, color: "#888" }}>场地目录加载中…</div>
        )}
        {Object.entries(venues).map(([vid, v]) => (
          <div
            key={vid}
            style={{
              border: "1px solid var(--line)", borderRadius: 10, padding: 10,
              background: "#fafafa",
            }}
          >
            <div style={{ fontSize: 14 }}>
              {typeIcon[v.type] || "📍"} <b>{v.name}</b>
            </div>
            <div style={{ fontSize: 12, color: "#888", margin: "4px 0" }}>
              {v.location} · 容量 {v.capacity} 人
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 6, gap: 6 }}>
              <span
                style={{
                  fontSize: 11, padding: "2px 8px", borderRadius: 10,
                  background: v.auto_approve ? "#dcfce7" : "#ffedd5",
                  color: v.auto_approve ? "#16a34a" : "#ea580c",
                }}
              >
                {v.approval}
              </span>
              <button className="btn btn-ghost btn-sm" onClick={() => setPicked(vid)}>
                预约此场地
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
