### List all S3 buckets

```python3
from madeira import s3                                                                                                       
s3w = s3.S3()                                                                                                        
all_buckets = s3w.get_all_buckets()                                                                                                         
print(all_buckets)

# output:
# ['bucketone', 'buckettwo', 'bucketthree']
```

