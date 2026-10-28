"""Run Ultralytics object detection on a USB webcam (Raspberry Pi or desktop)."""

from __future__ import annotations

import argparse
import platform
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect objects from a USB camera using an Ultralytics YOLO model."
    )
    parser.add_argument(
        "--model",
        default=str(ROOT / "best.pt"),
        help="Path to the trained YOLO .pt model (default: best.pt beside this script).",
    )
    parser.add_argument(
        "--camera", type=int, default=0, help="USB camera index, usually 0 for /dev/video0."
    )
    parser.add_argument("--width", type=int, default=640, help="Requested camera width.")
    parser.add_argument("--height", type=int, default=480, help="Requested camera height.")
    parser.add_argument(
        "--imgsz", type=int, default=416, help="Inference image size; lower values can run faster."
    )
    parser.add_argument(
        "--conf", type=float, default=0.35, help="Minimum detection confidence from 0 to 1."
    )
    parser.add_argument(
        "--classes",
        help="Comma-separated class names or IDs, e.g. person,car or 0,2. Default: all classes.",
    )
    parser.add_argument(
        "--device", default="cpu", help="Inference device (default: cpu; e.g. 0 for CUDA)."
    )
    parser.add_argument(
        "--no-display",
        action="store_true",
        help="Run without an OpenCV window and print detections to the terminal.",
    )
    return parser.parse_args()


def resolve_classes(spec: str | None, names: Any) -> list[int] | None:
    if not spec:
        return None

    if isinstance(names, dict):
        class_names = {int(class_id): str(name) for class_id, name in names.items()}
    else:
        class_names = {i: str(name) for i, name in enumerate(names)}
    name_to_id = {name.lower(): class_id for class_id, name in class_names.items()}

    class_ids: list[int] = []
    for value in spec.split(","):
        value = value.strip()
        if not value:
            continue
        if value.isdecimal():
            class_id = int(value)
            if class_id not in class_names:
                raise ValueError(f"Class ID {class_id} is not in this model: {class_names}")
        else:
            try:
                class_id = name_to_id[value.lower()]
            except KeyError as exc:
                available = ", ".join(class_names.values())
                raise ValueError(
                    f"Unknown class '{value}'. Classes in this model: {available}"
                ) from exc
        if class_id not in class_ids:
            class_ids.append(class_id)

    if not class_ids:
        raise ValueError("No valid class was provided to --classes.")
    return class_ids


def main() -> int:
    args = parse_args()
    model_path = Path(args.model).expanduser()
    if not model_path.is_file():
        print(
            f"Không tìm thấy model: {model_path}\n"
            "Hãy chép best.pt vào cùng thư mục với detect_camera.py "
            "hoặc truyền đường dẫn bằng --model.",
            file=sys.stderr,
        )
        return 2
    if not 0.0 <= args.conf <= 1.0:
        print("--conf phải nằm trong khoảng 0 đến 1.", file=sys.stderr)
        return 2

    try:
        import cv2
        from ultralytics import YOLO
    except ImportError as exc:
        print(
            f"Thiếu thư viện: {exc}. Cài bằng: python -m pip install ultralytics opencv-python",
            file=sys.stderr,
        )
        return 2

    try:
        model = YOLO(str(model_path))
        class_ids = resolve_classes(args.classes, model.names)
    except Exception as exc:
        print(f"Không tải được model hoặc lớp cần detect: {exc}", file=sys.stderr)
        return 2

    # V4L2 is the normal Linux camera interface used by USB webcams on Raspberry Pi OS.
    if platform.system() == "Linux" and hasattr(cv2, "CAP_V4L2"):
        camera = cv2.VideoCapture(args.camera, cv2.CAP_V4L2)
    else:
        camera = cv2.VideoCapture(args.camera)

    camera.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    if not camera.isOpened():
        print(
            f"Không mở được camera index {args.camera}. Hãy kiểm tra webcam và thử --camera 1.",
            file=sys.stderr,
        )
        camera.release()
        return 1

    print(f"Model: {model_path}")
    print(f"Camera: {args.camera}; classes: {class_ids if class_ids is not None else 'all'}")
    print("Nhấn Q hoặc Esc để thoát." if not args.no_display else "Nhấn Ctrl+C để thoát.")

    previous_time = time.perf_counter()
    last_console_update = previous_time
    fps = 0.0

    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                print("Không đọc được hình ảnh từ camera.", file=sys.stderr)
                break

            try:
                result = model.predict(
                    source=frame,
                    imgsz=args.imgsz,
                    conf=args.conf,
                    classes=class_ids,
                    device=args.device,
                    verbose=False,
                )[0]
            except Exception as exc:
                print(f"Lỗi khi chạy nhận diện: {exc}", file=sys.stderr)
                break

            now = time.perf_counter()
            elapsed = now - previous_time
            if elapsed > 0:
                fps = 1.0 / elapsed
            previous_time = now

            if args.no_display:
                if now - last_console_update >= 1.0:
                    boxes = result.boxes
                    if boxes is None or len(boxes) == 0:
                        print("Không phát hiện vật thể.")
                    else:
                        detections = []
                        for box in boxes:
                            class_id = int(box.cls.item())
                            label = result.names[class_id]
                            confidence = float(box.conf.item())
                            detections.append(f"{label} {confidence:.2f}")
                        print("Phát hiện: " + ", ".join(detections))
                    last_console_update = now
                continue

            annotated = result.plot()
            cv2.putText(
                annotated,
                f"FPS: {fps:.1f}",
                (12, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )
            cv2.imshow("SafeStep - Object Detection", annotated)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
    except KeyboardInterrupt:
        print("\nĐã dừng theo yêu cầu.")
    finally:
        camera.release()
        if not args.no_display:
            cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
