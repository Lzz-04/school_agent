import { useCallback, useState } from "react";
import { api } from "../../api/client";
import { toast } from "../../store/toast";
import type { FormDraft, SubmitInfo } from "./formTypes";

export type SubmitOutcome = { summary: string; info: SubmitInfo };

/**
 * 表单卡片公共状态机：editing / submitted / cancelled + busy + 结果落库。
 *
 * finish 执行实际提交（字段校验与 payload 构造由调用方负责），成功后统一：
 * 更新摘要与结构化信息、写回消息 form_draft（saveInfo=true 时额外保存 info）、toast 提示。
 * 与原四个表单卡片的提交尾部行为保持一致。
 */
export function useFormSubmit(draft: FormDraft, messageId?: string) {
  const [state, setState] = useState<"editing" | "submitted" | "cancelled">(
    draft._submitted ? "submitted" : draft._cancelled ? "cancelled" : "editing"
  );
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(draft.result || "");
  const [info, setInfo] = useState<SubmitInfo | null>(draft.info || null);

  const finish = useCallback(
    async (submitFn: () => Promise<SubmitOutcome>, saveInfo = false) => {
      setBusy(true);
      try {
        const { summary, info: infoOut } = await submitFn();
        setResult(summary);
        setInfo(infoOut);
        setState("submitted");
        if (messageId) {
          const body: Record<string, unknown> = { result: summary, request_no: infoOut.request_no };
          if (saveInfo) body.info = infoOut;
          api.chatSaveFormResult(messageId, body).catch(() => {});
        }
        toast("提交成功：" + infoOut.request_no, "ok");
      } catch (e: any) {
        toast(e.message || "提交失败", "err");
      } finally {
        setBusy(false);
      }
    },
    [messageId]
  );

  const cancel = useCallback(() => {
    setState("cancelled");
    if (messageId) api.chatSaveFormResult(messageId, { cancelled: true }).catch(() => {});
  }, [messageId]);

  return { state, busy, result, info, setState, finish, cancel };
}
