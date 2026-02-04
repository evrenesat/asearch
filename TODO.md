# TODO


  

Expermiental Tools
link_extractor tool:
 When we give this tool accept URLs and returns all the links and only links to the model. Links and their labels.
 But we store textual body of the content in the database as a cache for the URL. But we don't share it immediately with the model. Instead we share the links with the model. And we ask model again if it wants to
 retrieve more links from those links more deep into the links. If it decides if it wants it provides back more links and we retrieve those links as well.
 the problem we are trying to solve with this concept is reducing token usage. so if we should guide the model to collect enough
 amount of links and it should decide on if it wants to visit a link or not based on its label and URL and once it decides that okay I want to read those links we give it all of them
 at once or or we create summaries for those links the contents of those links and first we show short summaries what those links involve then it decides to actually see details this is actually very similar
 how a real person would do research we generally skim on multiple pages when we are doing research and then we select some to properly read and extract information

 - RAG

 - [] Read custom prompt from file path. 

 - [] I want to introduce a data_push tool for making get or post request to any URLs with the final result.


```toml

[push_data.post_to_my_blog]
method = "post" # or get
[push_data.post_to_my_blog.fields]
my_field="some_content"
my_api_key_env="MY_API_KEY"

```

