"""Run the ingest Lambda locally: live NUSMods data, in-memory S3 (moto).

Nothing touches AWS. The handler runs twice to check that an unchanged second
run writes nothing, then the fake bucket is copied to disk for inspection.

    cd backend
    poetry run python scripts/ingest_local.py                 # today's semester
    poetry run python scripts/ingest_local.py --date 2027-02-01
"""

import argparse
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

import boto3
from moto import mock_aws

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from handlers.ingest import handler

BUCKET = "lecturekaki-local-web"
REGION = "ap-southeast-1"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--date",
        default=date.today().isoformat(),
        help="any date in the semester to ingest (default: today)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=BACKEND / "out" / "ingest",
        help="where to copy the bucket contents (default: backend/out/ingest)",
    )
    args = parser.parse_args()

    os.environ["WEB_BUCKET"] = BUCKET
    with mock_aws():
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )

        event = {"date": args.date}
        print(f"Run 1 {event}")
        print(json.dumps(handler(event, None, s3=s3), indent=2))
        print("Run 2 (same data, expect written: 0)")
        print(json.dumps(handler(event, None, s3=s3), indent=2))

        if args.out.exists():
            shutil.rmtree(args.out)
        count = 0
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET):
            for obj in page.get("Contents", []):
                path = args.out / obj["Key"]
                path.parent.mkdir(parents=True, exist_ok=True)
                body = s3.get_object(Bucket=BUCKET, Key=obj["Key"])["Body"].read()
                path.write_bytes(body)
                count += 1
        print(f"Copied {count} files to {args.out}")


if __name__ == "__main__":
    main()
