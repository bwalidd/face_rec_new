from ultralytics import YOLO

# Load a model
model = YOLO("./ppl.pt")  # load a pretr
model.export(format="engine")  