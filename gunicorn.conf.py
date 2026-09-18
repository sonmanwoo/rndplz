import os
bind = "0.0.0.0:" + os.environ.get("PORT", "10000")
workers = 1
worker_class = "gthread"
threads = 8
timeout = 200
graceful_timeout = 30
accesslog = None
errorlog = "-"
limit_request_line = 4094
limit_request_fields = 50
limit_request_field_size = 4096

# This release includes the two explicitly approved profile cards.
raw_env = ["RNDPLZ_PUBLISH_PERSONAL=1"]
