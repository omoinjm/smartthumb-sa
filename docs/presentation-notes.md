# Friday presentation — 10 minutes

| # | Section (time) | What to say / show |
|---|---|---|
| 1 | Intro (1 min) | Team names, **SmartThumb SA**: automatic product-photo thumbnails + AI label suggestions for small online sellers. |
| 2 | Problem (1 min) | Sellers photograph stock on their phones for WhatsApp Business, Instagram and online catalogues, then resize and sort the photos by hand. Inconsistent sizes and no descriptions make the catalogue messy. *Quote any seller interviews; say it's a hypothesis if you didn't validate it.* |
| 3 | Solution (1 min) | Upload a photo, get a ≤300 px thumbnail plus suggested labels in about 2 s. Serverless, so it costs nothing while idle and fractions of a cent per image. Labels are suggestions for a human to review. |
| 4 | Live demo (3 min) | ① Open the live URL, upload a real product photo, show the original vs thumbnail, the % saved and the labels. ② Upload a fake .jpg and show it rejected with a reason. ③ Logs tab: the same events live from CloudWatch. ④ Test suite: *Run all checks*, 7/7 green. ⑤ Gallery: the whole team's results and label votes. *Backup: screenshots in docs/ in case of Wi-Fi trouble.* |
| 5 | Tech (1 min) | Terraform, S3 (2 private buckets), Lambda Python 3.12 + Pillow layer, Rekognition, API Gateway, IAM least privilege, CloudWatch. Hardest part: browser uploads straight to private S3 (presigned POST + CORS + regional endpoint) and packaging Pillow for Lambda. |
| 6 | Challenges (1 min) | Avoiding the recursive trigger (separate buckets). Validating by content, not extension. Rekognition not available in Cape Town, so we use eu-west-1. Flat PNGs can get *bigger*. Logs lag CloudWatch by a few seconds. |
| 7 | Close + Q&A (2 min) | Results table from the README (real numbers). Next: Cognito accounts, DynamoDB catalogue, WhatsApp catalogue export, background removal. |

Likely questions: Why two buckets? What does it cost per 100 images? What if Rekognition is wrong? How is it secured? What happens on duplicate events (it's idempotent: the same key overwrites the same output)?
