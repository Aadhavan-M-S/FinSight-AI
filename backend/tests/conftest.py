import os
import tempfile

storage = tempfile.TemporaryDirectory(prefix="finsight-test-")
os.environ["FINSIGHT_DATA_DIR"] = storage.name
os.environ["DENSE_RETRIEVAL"] = "false"
os.environ["LLM_PROVIDER"] = "mock"
