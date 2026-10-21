# CLAUDE.md

<!-- Giữ file này NGẮN. Với mỗi dòng, hỏi: "bỏ dòng này thì agent có làm sai không?" Không thì xoá.
     Rule nào biến được thành check hay hook thì chuyển sang đó và ghi vào bảng cuối file. -->

## Dự án

Bot tự trả lời Facebook Messenger cho hệ thống mầm non Casa dei Bambini (Hà Nội). FastAPI trong `app/main.py`; chuỗi AI dự phòng trong `app/ai_engine.py`; kiến thức tư vấn ở `data/qa_database.json` (`app/qa_database.py`); câu khó chuyển admin qua Telegram (`app/escalation.py`); hồ sơ khách ở `data/customers.json` (`app/customer_memory.py`). Render deploy từ nhánh `main`.

## Lệnh

- `./scripts/check.sh` là THE check: kiểm bộ kit cộng check của dự án (`scripts/check.local.sh`: compile `app/` + `pytest`). Chạy trước khi báo xong.
- Môi trường: `python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt`. Phiên cloud tự làm việc này qua `.claude/hooks/session-start.sh`.
- Một test: `.venv/bin/python -m pytest tests/test_smoke.py::test_health_check_reports_loaded_qa -q`
- Chạy app local: `uvicorn app.main:app --reload --port 8000`. Thử hội thoại không qua Facebook: `POST /test-chat?secret=<TELEGRAM_WEBHOOK_SECRET>` (cần ít nhất một API key AI trong `.env`; chỉ ghi `data/customers.json` cục bộ, không đẩy lên GitHub). Chấm hội thoại với model thật: `.venv/bin/python scripts/eval_chat.py` (exit 2 khi chưa có API key).
- Kiểm chứng trên app thật (verifier): skill `.claude/skills/verify-casa-bot/` — chạy bot cách ly, mọi request ra ngoài về fake cục bộ; feature map trong `features/`.
- `./scripts/audit-agent.sh --since 7` dò sự cố từ file phiên; `/agent-audit` dò rồi sửa kèm test, mở PR nháp.

## Cách làm việc

- Task không tầm thường thì dùng `/team-lead <task>`. Luôn chốt điều kiện xong dạng pass/fail trước khi làm.
- Bug: tái hiện trước (test fail hoặc bằng chứng), rồi mới sửa. Sửa nguyên nhân gốc.
- "Xong" nghĩa là `./scripts/check.sh` exit 0 cộng bằng chứng hành vi. Không chạy được check thì nói "inconclusive".
- Người viết không tự kiểm: verify và review bằng subagent mới (`verifier`, `reviewer`).
- Commit nhỏ, có thứ tự, theo Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`).
- Bị người dùng sửa cùng một lỗi lần thứ hai thì đề xuất `/correct`.

## Quyền tự chủ

- Cứ làm: đọc, sửa trong branch hoặc worktree, commit cục bộ, chạy test, mở PR nháp.
- Luôn hỏi người: force-push, push hoặc merge vào `main` (push lên `main` là deploy), xoá dữ liệu, deploy, publish, gửi tin nhắn thật cho phụ huynh.
- `data/customers.json` là dữ liệu cá nhân của phụ huynh và trẻ: không chép vào log, test, PR hay câu trả lời.

## Rule ↔ Thứ thực thi

| Rule | Thực thi bởi |
|---|---|
| Không kết thúc lượt khi check đỏ | `.claude/hooks/stop-gate.sh` (Stop) |
| Hỏi người trước hành động không đảo ngược được | `.claude/hooks/guard-irreversible.sh` (PreToolUse) |
| Không đọc file bí mật (`.env`, `*.pem`, `secrets/`) | `permissions.deny` trong `.claude/settings.json` |
| Format theo cấu hình của dự án | `.claude/hooks/post-edit-format.sh` (PostToolUse) |
| Phiên cloud có đủ dependency để chạy check | `.claude/hooks/session-start.sh` (SessionStart) |
| Agent và skill có frontmatter hợp lệ, link không gãy | `scripts/validate-kit.sh` (trong `check.sh`) |
| Không bớt ca "phải hỏi" của guard để cho dễ | `scripts/guard-ask-floor` (test-hooks đỏ khi số ca dưới sàn) |
| Bug phải được tái hiện trước khi sửa | Chỉ có lời nhắc (playbook bug-fix). Ứng viên cho `/correct` |
