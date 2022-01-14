---
title: Content-based Image Retrieval
type: templates
category: Ranking and Scoring
cat: ranking-and-scoring
order: 504
meta_title: 
meta_description: 
---



## Labeling Configuration

```html
<View>
  <Image name="query" value="$query_image" />
  <Header value="Choose similar images:" />
  <View style="display: grid; column-gap: 8px; grid-template: auto/1fr 1fr 1fr">
    <Image name="image1" value="$image1" />
    <Image name="image2" value="$image2" />
    <Image name="image3" value="$image3" />
  </View>
  <Choices name="similar" toName="query" required="true" choice="multiple">
    <Choice value="One" />
    <Choice value="Two" />
    <Choice value="Three" />
  </Choices>
  <Style>
    [dataneedsupdate]~div form {display: flex}
    [dataneedsupdate]~div form>* {flex-grow:1;margin-left:8px}
  </Style>
</View>
```

## Related tags

- [Image](/tags/image.html)
- [Choices](/tags/choices.html)
- [Style](/tags/style.html)